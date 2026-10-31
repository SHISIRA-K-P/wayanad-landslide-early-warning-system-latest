# Project Documentation

This folder documents the **implemented code** in the Wayanad Landslide Early
Warning and Response System. It also labels ideas mentioned in the repository
README as planned when they are not implemented in the current source.

## Documentation index

**Submission copy:** [Wayanad Landslide Project Documentation (.docx)](./Wayanad_Landslide_Project_Documentation.docx)

1. [Project Overview](./Project_Overview.md) — purpose, current features, stack,
   and high-level architecture.
2. [Project Setup Guide](./Project_Setup_Guide.md) — local prerequisites,
   configuration, database setup, and run commands.
3. [System Architecture](./System_Architecture.md) — frontend, backend,
   database, ML, RAG, response-agent, and Power BI status.
4. [Application Workflow](./Application_Workflow.md) — ordered end-to-end
   observation and safety-assistant workflows.
5. [Backend Documentation](./Backend_Documentation.md) — Django modules,
   functions, classes, endpoints, and JSON shapes.
6. [AI/ML Documentation](./AI_ML_Documentation.md) — prediction artifact,
   training notebook, RAG indexing/retrieval, Ollama, and CrewAI.
7. [Frontend Documentation](./Frontend_Documentation.md) — React component
   structure, API calls, result display, and records view.
8. [Database Documentation](./Database_Documentation.md) — current Django
   tables, fields, constraints, and example SQL.
9. [Email Notification Workflow](./Email_Notification_Workflow.md) — contact
   selection, SMTP setup, message construction, and failure behavior.
10. [Troubleshooting Guide](./Troubleshooting_Guide.md) — common local
    environment and service issues.

## Important safety note

This is a **learning prototype**, not an officially validated early-warning
system. Model outputs are estimates. Do not rely on this application to make
emergency decisions or replace instructions from local authorities and
emergency services.
