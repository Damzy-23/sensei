"""Voice transport. Cross-cutting: not one of the six building blocks.

The voice agent runs on ElevenLabs and acts on the page through typed page tools
(web/src/agent/). It never answers a problem question itself: it calls the same turn
loop as the text chat, so guards, the hint ladder and tracing all still apply.

The provider key stays on the server. The browser gets a short-lived signed URL.
"""
