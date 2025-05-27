# Telegram Channel Indexer

A high-performance, real-time Telegram channel indexing system built with FastAPI, Celery, and Elasticsearch. This application provides comprehensive monitoring, data storage, and search capabilities for Telegram channel content.

## 🚀 Features

- **Real-time Message Indexing**: Automatically indexes messages from Telegram channels
- **Elasticsearch Integration**: Full-text search and advanced querying capabilities
- **Image Processing**: Handles and stores media content using MinIO object storage
- **Asynchronous Processing**: Celery-powered background task processing
- **Smart Synchronization**: Intelligent sync mechanisms for data consistency
- **Comprehensive Monitoring**: Prometheus metrics with Grafana dashboards
- **RESTful API**: FastAPI-based endpoints for data access and management
- **Scalable Architecture**: Docker-based microservices architecture

## 🏗️ System Architecture

The application follows a microservices architecture with the following components:

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   FastAPI App   │    │  Celery Worker  │    │   Elasticsearch │
│                 │    │                 │    │                 │
│  - API Routes   │◄──►│  - Background   │◄──►│  - Full-text    │
│  - Data Access  │    │    Tasks        │    │    Search       │
│  - Monitoring   │    │  - Message      │    │  - Data Storage │
└─────────────────┘    │    Processing   │    └─────────────────┘
         │              └─────────────────┘             │
         ▼                       │                      ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│      MinIO      │    │      Redis      │    │   Prometheus    │
│                 │    │                 │    │                 │
│  - Object       │    │  - Message      │    │  - Metrics      │
│    Storage      │    │    Broker       │    │    Collection   │
│  - Media Files  │    │  - Task Queue   │    │  - Monitoring   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## 🔄 Request Processing Workflow

The system processes requests through the following workflow:

1. **Client Request** lands at the FastAPI web server
2. If needed, the server enqueues a long-running job via **Redis**
3. A **Celery Worker** picks up the job, processes it, and reports status/results
4. The server logs or returns the outcome to the client, completing the cycle

## 📋 Prerequisites

Before setting up the application, ensure you have:

- **Docker & Docker Compose** installed
- **Python 3.10+** (for local development)
- **Telegram API credentials** (API ID, API Hash, Session String)

## 🛠️ Installation & Setup

### **Step 1: Clone the Repository**

```bash
git clone https://github.com/adelabdelgawad/teleye.git
cd teleye
```

### **Step 2: Obtain Telegram Credentials**

#### **Getting API ID and API Hash**

1. Visit [my.telegram.org](https://my.telegram.org)
2. Log in with your phone number
3. Navigate to "API Development Tools"
4. Create a new application to get your `api_id` and `api_hash`

#### **Generating Session String**

Create a Python script to generate your session string:

```python
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

TELEGRAM_API_ID = your_api_id_here
TELEGRAM_API_HASH = "your_api_hash_here"

with TelegramClient(
    StringSession(), TELEGRAM_API_ID, TELEGRAM_API_HASH
) as client:
    print(client.session.save())  # Copy this string and store it securely
```

**Execution Steps:**

1. Install telethon: `pip install telethon`
2. Replace `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` with your actual credentials
3. Run the script
4. Enter your phone number when prompted
5. Enter the verification code sent to your Telegram account
6. Copy the generated session string from the output

**⚠️ Security Warning:**
- **Never share your session string** - it provides full access to your Telegram account
- Store the session string securely using environment variables or secure vaults
- The session string is equivalent to your login credentials

### **Step 3: Environment Configuration**

Create a `.env` file in the `app/` directory:

```env
# Telegram Configuration
TELEGRAM_API_ID=your_api_id_here
TELEGRAM_API_HASH=your_api_hash_here
TELEGRAM_STRING_SESSION=your_generated_session_string_here

# MinIO Configuration
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin123
MINIO_ENDPOINT=minio:9000
MINIO_SECURE=false
MINIO_USE_PRESIGNED_URLS=true

# Redis Configuration
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# Elasticsearch Configuration
ELASTICSEARCH_CONNECTION_URL=http://elasticsearch:9200

# API Configuration
API_TITLE=Telegram Channel Indexer
API_DESCRIPTION=Real-time message collection from Telegram channels
API_VERSION=1.0.0

# Flower Configuration
FLOWER_PORT=5555

# Security: Default Admin Credentials
SECURITY_ADMIN_USERNAME=admin
SECURITY_ADMIN_PASSWORD=SuperSecurePass123
SECURITY_SECRET_KEY=your_jwt_secret
SECURITY_ALGORITHM=HS256
SECURITY_ACCESS_TOKEN_EXPIRE_MINUTES=60
```

### **Step 4: Launch the Application**

```bash
# Start all services
docker-compose up -d

# View real-time logs
docker-compose logs -f

# Check service status
docker-compose ps
```

## 🌐 Service Access Points

| Service | URL | Description | Credentials |
|---------|-----|-------------|-------------|
| **FastAPI API** | http://localhost:8000 | Main application API | - |
| **API Documentation** | http://localhost:8000/docs | Interactive Swagger UI | - |
| **Flower Monitor** | http://localhost:5555 | Celery task monitoring | - |
| **Grafana Dashboard** | http://localhost:3000 | Application monitoring | admin/admin |
| **Prometheus** | http://localhost:9090 | Metrics collection | - |
| **MinIO Console** | http://localhost:9001 | Object storage management | minioadmin/minioadmin123 |
| **Elasticsearch** | http://localhost:9200 | Search engine API | - |

## 🔧 API Reference

### **Channel Management**

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `GET` | `/channels/` | List all channels | ✅ |
| `POST` | `/channels/` | Add new channel | ✅ (Admin) |
| `GET` | `/channels/{channel_id}` | Get channel details | ✅ |
| `DELETE` | `/channels/{channel_id}` | Remove channel | ✅ (Admin) |

### **Message Operations**

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `GET` | `/messages/` | Search messages | ✅ |
| `GET` | `/messages/{message_id}` | Get specific message | ✅ |
| `POST` | `/messages/search` | Advanced search | ✅ |

### **Synchronization**

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/sync/start` | Start sync process | ✅ (Admin) |
| `GET` | `/sync/status` | Check sync status | ✅ |
| `POST` | `/sync/smart` | Smart synchronization | ✅ (Admin) |

### **Listener Management**

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/listeners/start` | Start message listener | ✅ (Admin) |
| `POST` | `/listeners/stop` | Stop message listener | ✅ (Admin) |
| `GET` | `/listeners/status` | Get listener status | ✅ |

### **Authentication & User Management**

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/auth/token` | Obtain JWT access token | - |
| `POST` | `/users` | Create new user | ✅ (Admin) |
| `PUT` | `/users/{username}` | Update user | ✅ (Admin) |
| `DELETE` | `/users/{username}` | Delete user | ✅ (Admin) |

## 🔒 Security & Authorization

### **Authentication System**

The application uses **OAuth2 Password (Bearer)** tokens with JWT for authentication:

1. Obtain a token via `POST /auth/token` with valid credentials
2. Include the token in the `Authorization` header: `Bearer `
3. Tokens expire based on the configured timeout (default: 60 minutes)

### **Role-Based Access Control**

The system supports two distinct roles with different permissions:

| Role | Permissions |
|------|-------------|
| **User** | **Read Operations:**- View channels and messages- Search functionality- Check sync and listener status |
| **Admin** | **All User Permissions Plus:**- Create/delete channels- Start/stop synchronization- Control message listeners- Full user management |

**Error Responses:**
- **401 Unauthorized**: Missing or invalid token
- **403 Forbidden**: Insufficient permissions for the requested operation

## 👀 Monitoring & Observability

### **Grafana Dashboards**

Access comprehensive monitoring at http://localhost:3000 (admin/admin):

- **FastAPI Dashboard**: Request metrics, response times, error rates
- **Celery Dashboard**: Task execution, worker status, queue monitoring

### **Prometheus Metrics**

The application exposes detailed metrics including:

- **API Metrics**: Request/response times, status codes, endpoint usage
- **Task Metrics**: Success/failure rates, execution times, queue lengths
- **Worker Metrics**: Performance, availability, resource consumption
- **System Metrics**: Memory usage, CPU utilization, disk I/O
- **Error Tracking**: Exception rates, failure patterns

## 🧪 Testing

Execute the comprehensive test suite:

```bash
# Run all tests
docker-compose exec app pytest

# Run with coverage report
docker-compose exec app pytest --cov=app

# Run specific test module
docker-compose exec app pytest tests/test_channel_router.py

# Run tests with verbose output
docker-compose exec app pytest -v
```

## 📁 Project Structure

```
app/
├── core/
│   ├── config.py           # Application configuration & settings
│   └── models.py           # Pydantic data models
├── routers/
│   ├── channel_router.py   # Channel management endpoints
│   ├── message_router.py   # Message operations & search
│   ├── sync_router.py      # Synchronization controls
│   ├── listener_router.py  # Real-time message listening
│   └── auth_router.py      # Authentication & user management
├── services/
│   ├── auth_service.py     # JWT authentication & password hashing
│   ├── elasticsearch.py   # Search engine operations
│   ├── minio_service.py    # Object storage management
│   └── listener_service.py # Telegram client integration
├── tasks/
│   ├── channel_tasks.py    # Asynchronous channel processing
│   ├── message_tasks.py    # Background message handling
│   └── sync_tasks.py       # Synchronization task workers
└── tests/                  # Comprehensive test suite
    ├── test_auth.py        # Authentication tests
    ├── test_channels.py    # Channel management tests
    └── test_messages.py    # Message processing tests
```

## 🆘 Troubleshooting

### **Common Issues & Solutions**

**Services Not Starting**
```bash
# Check service logs
docker-compose logs [service_name]

# Restart specific service
docker-compose restart [service_name]

# Rebuild and restart
docker-compose up --build -d
```

**Permission Errors**
```bash
# Fix file ownership
sudo chown -R $USER:$USER .

# Set proper permissions
chmod -R 755 .
```

**Port Conflicts**
```bash
# Check port usage
netstat -tulpn | grep [port_number]

# Kill process using port
sudo kill -9 $(lsof -t -i:[port_number])
```

**Database Connection Issues**
```bash
# Check Elasticsearch health
curl http://localhost:9200/_cluster/health

# Verify Redis connectivity
docker-compose exec redis redis-cli ping
```

## 🤝 Contributing

We welcome contributions! Please follow these steps:

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/amazing-feature`)
3. **Commit** your changes (`git commit -m 'Add amazing feature'`)
4. **Push** to the branch (`git push origin feature/amazing-feature`)
5. **Open** a Pull Request

### **Development Guidelines**

- Follow PEP 8 style guidelines
- Write comprehensive tests for new features
- Update documentation for API changes
- Use meaningful commit messages
- Ensure all tests pass before submitting

## 📞 Support & Community

**Getting Help:**
- 🐛 **Bug Reports**: Open an issue with detailed reproduction steps
- 💡 **Feature Requests**: Describe your use case and proposed solution
- 📚 **Documentation**: Check `/docs` endpoint for API reference
- 🔍 **Debugging**: Examine container logs for error details


## 📝 License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for complete details.

---

**Built with ❤️ using FastAPI, Celery, Elasticsearch, and Docker**
