try:
    import langchain  # type: ignore

    if not hasattr(langchain, "verbose"):
        langchain.verbose = False  # type: ignore[attr-defined]
    if not hasattr(langchain, "debug"):
        langchain.debug = False  # type: ignore[attr-defined]
except Exception:
    pass
