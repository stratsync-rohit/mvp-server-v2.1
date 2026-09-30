"""Safe application exceptions."""


class AppError(Exception):
    """Safe HTTP-facing application error."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class DomainError(Exception):
    """Base exception for provider-independent business failures."""


class ConfigurationError(DomainError):
    """Raised when an internal operation lacks required configuration."""


class ProviderError(DomainError):
    """Raised when a Microsoft provider operation cannot be completed."""


class PersistenceError(DomainError):
    """Raised when an internal persistence boundary cannot be used."""
