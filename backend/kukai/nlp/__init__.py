"""KUKAI NLP primitives — the lemma-normalized Russian lexicon (IQ-moment #7).

One morphology function for every RU keyword table, instead of 3+ divergent
hand-enumerated declension lists. Import from the submodule::

    from kukai.nlp.lemma import lemma, lemma_phrase, lemma_lexicon_enabled

Deliberately NO re-exports here: ``lemma`` (the function) would shadow
``kukai.nlp.lemma`` (the submodule) as a package attribute, breaking
``import kukai.nlp.lemma as L`` for tests and tooling.
"""
