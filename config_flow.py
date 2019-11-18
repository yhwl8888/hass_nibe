"""Nibe uplink configuration."""

import logging
from typing import Dict  # noqa
import voluptuous as vol
from aiohttp.web import Request, Response, HTTPBadRequest

from homeassistant import config_entries, data_entry_flow
from homeassistant.components.http import HomeAssistantView

from nibeuplink import UplinkSession

from .const import (
    AUTH_CALLBACK_NAME,
    AUTH_CALLBACK_URL,
    CONF_ACCESS_DATA,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_REDIRECT_URI,
    CONF_UPLINK_APPLICATION_URL,
    CONF_WRITEACCESS,
    DATA_NIBE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
_view = None


@config_entries.HANDLERS.register(DOMAIN)
class NibeConfigFlow(config_entries.ConfigFlow):
    """Conflig flow for nibe uplink."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self):
        """Init."""
        self.access_data = None
        self.user_data = None

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        if user_input:
            scope = None
            if user_input[CONF_WRITEACCESS]:
                scope = ["READSYSTEM", "WRITESYSTEM"]
            else:
                scope = ["READSYSTEM"]

            session = UplinkSession(
                client_id=user_input[CONF_CLIENT_ID],
                client_secret=user_input[CONF_CLIENT_SECRET],
                redirect_uri=user_input[CONF_REDIRECT_URI],
                scope=scope,
            )

            self.session = session
            self.user_data = user_input
            return await self.async_step_auth()

        url = "{}{}".format(self.hass.config.api.base_url, AUTH_CALLBACK_URL)

        config = self.hass.data[DATA_NIBE].config

        return self.async_show_form(
            step_id="user",
            description_placeholders={
                "application": CONF_UPLINK_APPLICATION_URL,
                "suffix": AUTH_CALLBACK_URL,
            },
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_REDIRECT_URI, default=config.get(CONF_REDIRECT_URI, url)
                    ): str,
                    vol.Required(
                        CONF_CLIENT_ID, default=config.get(CONF_CLIENT_ID, None)
                    ): str,
                    vol.Required(
                        CONF_CLIENT_SECRET, default=config.get(CONF_CLIENT_SECRET, None)
                    ): str,
                    vol.Required(
                        CONF_WRITEACCESS, default=config.get(CONF_WRITEACCESS, False)
                    ): bool,
                }
            ),
        )

    async def async_step_auth(self, user_input=None):
        """Handle authentication step."""
        _LOGGER.debug("Async step auth %s", user_input)

        errors = {}
        if user_input is not None:
            try:
                await self.session.get_access_token(user_input["code"])
            except Exception:
                _LOGGER.exception("Error on converting code")
                errors["base"] = "code"
            else:
                self.user_data[CONF_ACCESS_DATA] = self.session.access_data
                return self.async_external_step_done(next_step_id="finish")

        global _view
        if not _view:
            _view = NibeAuthView()
            self.hass.http.register_view(_view)

        url = self.session.get_authorize_url()
        _view.register_flow(self.session.state, self.flow_id)

        return self.async_external_step(step_id="auth", url=url)

    async def async_step_finish(self, user_data=None):
        """Just to finish up the external step."""
        if user_data is not None:
            return self.async_create_entry(title="Nibe Uplink", data=self.user_data)

        return self.async_show_form(step_id="finish", data_schema=vol.Schema({}))


class NibeAuthView(HomeAssistantView):
    """Handle nibe  authentication callbacks."""

    url = AUTH_CALLBACK_URL
    name = AUTH_CALLBACK_NAME

    requires_auth = False

    def __init__(self) -> None:
        """Initialize instance of the view."""
        super().__init__()
        self._flows = {}  # type: Dict[str, str]

    def register_flow(self, state, flow_id):
        """Register a flow in the view."""
        self._flows[state] = flow_id
        _LOGGER.debug("Register state %s for flow_id %s", state, flow_id)

    async def get(self, request: Request) -> Response:
        """Handle oauth token request."""
        hass = request.app["hass"]

        def check_get(param):
            if param not in request.query:
                _LOGGER.error("State missing in request.")
                raise HTTPBadRequest("Parameter {} not found".format(param))
            return request.query[param]

        state = check_get("state")
        code = check_get("code")

        if state not in self._flows:
            _LOGGER.error("State unexpected %s", state)
            raise HTTPBadRequest("State can not be translated into flow")

        flow_id = self._flows[state]
        _LOGGER.debug("Received auth request for flow %s", flow_id)

        try:
            await hass.config_entries.flow.async_configure(flow_id, {"code": code})

            return Response(
                headers={"content-type": "text/html"},
                text="<script>window.close()</script>",
            )
        except data_entry_flow.UnknownFlow:
            raise HTTPBadRequest("Unkown flow")
