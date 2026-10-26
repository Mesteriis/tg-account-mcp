# Dashboard screenshots

The README gallery uses browser captures of the implemented dashboard, rendered
with a synthetic local fixture. Account names, chat names, identifiers, counts,
timestamps and error states are fictional. No production captures are published here.
The UI is currently in Russian in both language versions of the README.

| Capture | Surface |
| --- | --- |
| [monitoring-desktop.png](monitoring-desktop.png) | RAG monitoring, facets, pagination and inline chat rule |
| [monitoring-settings.png](monitoring-settings.png) | Default RAG/S3 rules in Settings |
| [monitoring-mobile.png](monitoring-mobile.png) | Mobile RAG layout |
| [monitoring-mobile-editor.png](monitoring-mobile-editor.png) | Mobile inline editor and pagination |

`monitoring-reference.png` is an AI-generated design concept, not an application
screenshot. The paired images compare that concept to the implementation and are
used only as design QA evidence. See [the QA report](../../design-qa.md).

To refresh the gallery, use synthetic data in an isolated local instance of the
actual frontend. Never point the fixture at Telegram sessions or production state.
Review every capture for private titles, identifiers, URLs and secrets before
committing it. Keep the filenames stable so both README galleries stay in sync.
