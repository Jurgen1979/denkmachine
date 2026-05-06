"""enkelvoudige gebruiker voor flask-login (single-user systeem)."""

from flask_login import UserMixin


class SingleUser(UserMixin):
    """De enige gebruiker van het systeem, gedefinieerd via omgevingsvariabelen."""

    id = "1"

    def get_id(self) -> str:
        """Geef het gebruikers-id terug als string."""
        return self.id
