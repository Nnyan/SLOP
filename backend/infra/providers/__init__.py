"""Auto-import all infrastructure providers.
Each provider module uses the @register decorator from backend.infra.registry.
Importing this package makes all providers available to list_providers().
"""
# These imports trigger @register calls in each module.
# Order is display order in the UI.
from backend.infra.providers.auth_tinyauth import TinyauthProvider  # noqa: F401
from backend.infra.providers.tunnel_cloudflare import CloudflareTunnelProvider  # noqa: F401
from backend.infra.providers.tunnel_tailscale import TailscaleProvider  # noqa: F401
from backend.infra.providers.vpn_gluetun import GluetunProvider  # noqa: F401
from backend.infra.providers.dashboard_homepage import HomepageProvider  # noqa: F401
from backend.infra.providers.dashboard_glance import GlanceDashboardProvider  # noqa: F401
from backend.infra.providers.management_portainer import PortainerProvider  # noqa: F401
from backend.infra.providers.management_alternatives import (  # noqa: F401
    DockhandProvider, DockgeProvider, KomodoProvider, PortainerBEProvider,
)

__all__ = [
    "TinyauthProvider", "CloudflareTunnelProvider", "TailscaleProvider",
    "GluetunProvider", "HomepageProvider", "GlanceDashboardProvider",
    "PortainerProvider", "DockhandProvider", "DockgeProvider",
    "KomodoProvider", "PortainerBEProvider",
]
