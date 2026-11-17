"""The local HTTP API onto the working ontology, and what it is built from.

* :mod:`.service` — the query and edit operations, on any
  :class:`~.service.Workspace` (no web framework, no Streamlit).
* :mod:`.rest` — the FastAPI app over the service.
* :mod:`.server` — runs that app in a thread beside Streamlit and writes the
  discovery file the MCP server reads.
* :mod:`.bridge` — ties the running Streamlit session to the service: one
  lock for UI runs and API calls, and a refresh when the API changed things.

The MCP server (:mod:`orionbelt_ontology_builder.mcp_server`) is a separate
process and a client of the HTTP API, so it never touches the graph itself.

Everything here needs the ``api`` extra (FastAPI, uvicorn, MCP SDK), which the
base install and the Streamlit Cloud deployment do not pull in.
"""
