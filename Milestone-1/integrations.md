# Integration inventory

- **Core banking (REST over mainframe)** - transactions, dispute records via REST/JSON; owner the CISO (CISO gate); tech 2/5, political 5/5; must act as the analyst (OBO) - W16
- **Microsoft Entra ID** - identity / who is asking via OIDC / OAuth2; owner the CISO; tech 3/5, political 4/5; Entra Agent ID gives the agent its own identity - W16
- **Data warehouse (Azure)** - 18 months of history (W19) via SQL / PostgREST; owner the data lead (overloaded); tech 4/5, political 3/5; read-only role; W19 text-to-SQL target
- **ServiceNow** - tickets, duplicate disputes via REST/JSON; owner Ops IT; tech 3/5, political 2/5; service account; per-user scope later
- **SharePoint policy docs** - Reg E / GLBA policies (RAG source) via Graph API / export; owner Compliance; tech 2/5, political 2/5; read-only; one chunk is poisoned (W16)
