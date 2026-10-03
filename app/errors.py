"""Domain errors raised by the service layer; app.main maps them to HTTP responses."""


class ServiceError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFoundError(ServiceError):
    status_code = 404


class ConflictError(ServiceError):
    status_code = 409


class InvalidReferenceError(ServiceError):
    status_code = 422


class LoginRequired(Exception):
    """Raised by HTML page routes when no one is logged in; answered with a redirect."""
