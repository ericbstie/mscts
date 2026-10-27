"""How the client reads an identifier (`Identifier.parse`), for the Comparison and the Bot alike."""


def identifier_read(text: str) -> str:
    """`text` as the client reads it (`client_identifier`), or as sent if the client cannot."""
    return client_identifier(text) or text


def client_identifier(text: str) -> str | None:
    """`text` as the client's `Identifier.parse` reads it, with its namespace; None if it throws.

    (`Identifier.bySeparator`: with no `:`, or with one first, the path is the rest, in the
    `minecraft` namespace. `createUntrusted` and `withDefaultNamespace` then throw
    `IdentifierException` for a namespace or path that `isValidNamespace` or `isValidPath`
    refuses, which disconnects the client; javap on the 26.3 client.)
    """
    namespace, colon, path = text.partition(":")
    if not colon:
        namespace, path = "", text
    namespace = namespace or "minecraft"
    return f"{namespace}:{path}" if _valid_identifier(namespace, path) else None


def _valid_identifier(namespace: str, path: str) -> bool:
    """Whether `Identifier.isValidNamespace(namespace)` and `isValidPath(path)` both hold."""
    return (
        namespace != ".."
        and set(namespace) <= _NAMESPACE_CHARACTERS
        and set(path) <= _NAMESPACE_CHARACTERS | {"/"}
    )


_NAMESPACE_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_-.")
"""The characters `Identifier.validNamespaceChar` allows; `validPathChar` allows `/` too."""
