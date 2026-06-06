"""Phase 5 website discovery providers and verification gate.

Providers in this subpackage are admin-only, lead-generation helpers. They
never write a public ``mosque.website_url`` directly. Each provider returns
:class:`WebsiteLead` candidates, which the :func:`verify_website` gate
inspects before promotion.

The discovery flow is:

  select-mosques-without-website
        -> provider.propose_leads(mosque)
        -> verify_website(lead, ...)
             -> promote via manual source if moderate strictness passes
             -> else record as admin discovery lead
"""
