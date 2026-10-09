spicmacay-event-agent/
├── app/
│   ├── __init__.py              # Application factory
│   ├── config.py                # Configuration management
│   ├── models/
│   │   ├── agent.py            # Conversational AI agent
│   │   ├── database.py         # Database operations
│   │   └── notifications.py    # Email service
│   ├── routes/
│   │   ├── chat.py             # Chat API endpoints
│   │   ├── events.py           # Event management endpoints
│   │   └── dashboard.py        # Dashboard endpoints
│   ├── services/
│   │   ├── event_service.py    # Event business logic
│   │   └── validation_service.py
│   ├── static/
│   │   ├── css/style.css       # Stylesheet
│   │   └── js/
│   │       ├── chat.js         # Chat interface
│   │       └── dashboard.js    # Dashboard interface
│   └── templates/
│       ├── base.html
│       ├── chatbot.html        # Chat interface
│       └── dashboard.html      # Dashboard interface
├── migrations/
│   └── init_db.sql             # Database schema
├── tests/
│   ├── test_agent.py           # Agent tests
│   └── test_api.py             # API tests
├── .env.example                # Environment template
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── run.py                      # Application entry point
└── README.md
