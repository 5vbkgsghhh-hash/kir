"""lookup_norm handler — normative-document semantic search (extracted from client.py).

Pure relocation (2026-07-04 client.py decomposition, Step 2): the body is
byte-identical to the former ``LLMClient._execute_lookup_norm`` staticmethod
(zero ``self`` coupling). ``LLMClient`` rebinds it as a staticmethod so the
dispatch site and any callers keep working unchanged.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _execute_lookup_norm(args: dict[str, Any], active_extension: Optional[str] = None) -> dict[str, Any]:
    """Search normative documents (СП, ГОСТ, ПУЭ, ФЗ) using semantic search.

    When active_extension is set, results from that extension are boosted
    (sorted first) but cross-discipline results are still included.
    """
    import sqlite3
    from pathlib import Path

    query = args.get("query", "").strip()
    limit = min(int(args.get("limit", 5)), 15)

    if not query:
        return {"error": True, "message": "Empty query"}

    db_path = Path(__file__).parent.parent.parent.parent / "data" / "norms.db"
    emb_path = Path(__file__).parent.parent.parent.parent / "data" / "norms_embeddings.npz"

    if not db_path.exists():
        return {"error": True, "message": "Norms database not available"}

    db = None
    try:
        import numpy as _np
        from openai import OpenAI as _OAI

        _oai_key = os.environ.get('KUKAI_OPENAI_API_KEY', os.environ.get('OPENAI_API_KEY', ''))
        if not _oai_key or not emb_path.exists():
            # Fallback to keyword search
            db = sqlite3.connect(str(db_path))
            db.row_factory = sqlite3.Row
            if active_extension:
                # Boost: fetch extension-matched first, then others
                ext_rows = db.execute(
                    "SELECT document_name, extension_id, text FROM norm_chunks "
                    "WHERE text LIKE ? AND extension_id = ? LIMIT ?",
                    (f"%{query}%", active_extension, limit),
                ).fetchall()
                remaining = limit - len(ext_rows)
                other_rows = []
                if remaining > 0:
                    other_rows = db.execute(
                        "SELECT document_name, extension_id, text FROM norm_chunks "
                        "WHERE text LIKE ? AND extension_id != ? LIMIT ?",
                        (f"%{query}%", active_extension, remaining),
                    ).fetchall()
                rows = list(ext_rows) + list(other_rows)
            else:
                rows = db.execute(
                    "SELECT document_name, extension_id, text FROM norm_chunks WHERE text LIKE ? LIMIT ?",
                    (f"%{query}%", limit),
                ).fetchall()
            if not rows:
                return {"found": 0, "message": f"No results for '{query}'"}
            return {
                "found": len(rows),
                "results": [
                    {"document": r["document_name"], "extension": r["extension_id"], "text": r["text"][:500]}
                    for r in rows
                ],
            }

        # Semantic search
        emb_data = _np.load(str(emb_path), allow_pickle=False)
        vectors = emb_data['vectors']
        chunk_ids = emb_data['ids']

        _oai = _OAI(api_key=_oai_key)
        from kukai.config import get_settings as _gs2
        qresp = _oai.embeddings.create(model=_gs2().embedding_model, input=[query])
        qvec = _np.array(qresp.data[0].embedding, dtype=_np.float32)

        norms = _np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = _np.maximum(norms, 1e-10)
        qnorm = _np.linalg.norm(qvec)
        if qnorm == 0:
            return {"found": 0, "message": "Empty query embedding"}

        sims = (vectors @ qvec) / (norms.flatten() * qnorm)
        # Fetch extra candidates when extension is active (to ensure good coverage)
        fetch_limit = limit * 3 if active_extension else limit
        top_idx = _np.argsort(sims)[::-1][:fetch_limit]
        matched_ids = [str(chunk_ids[i]) for i in top_idx if sims[i] > 0.25]

        if not matched_ids:
            return {"found": 0, "message": f"No relevant norms found for '{query}'"}

        db = sqlite3.connect(str(db_path))
        db.row_factory = sqlite3.Row
        placeholders = ','.join(['?'] * len(matched_ids))
        rows = db.execute(
            f"SELECT id, extension_id, document_name, text FROM norm_chunks WHERE id IN ({placeholders})",
            matched_ids,
        ).fetchall()

        # Sort: extension-matched first (boosted), then by similarity order
        id_order = {mid: i for i, mid in enumerate(matched_ids)}
        if active_extension:
            sorted_rows = sorted(
                rows,
                key=lambda r: (0 if r["extension_id"] == active_extension else 1, id_order.get(r["id"], 999)),
            )
        else:
            sorted_rows = sorted(rows, key=lambda r: id_order.get(r["id"], 999))
        sorted_rows = sorted_rows[:limit]

        return {
            "found": len(sorted_rows),
            "results": [
                {
                    "document": r["document_name"],
                    "extension": r["extension_id"],
                    "text": r["text"][:800],
                }
                for r in sorted_rows
            ],
        }
    except Exception as e:
        logger.exception("Norm lookup error")
        return {"error": True, "message": "Ошибка поиска в нормативной базе"}
    finally:
        if db:
            db.close()
