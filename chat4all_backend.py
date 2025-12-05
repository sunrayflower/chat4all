#!/usr/bin/env python3
"""
Chat4All v2 - Backend Implementation with gRPC, Kafka, and WebSockets
Platform: Ubuntu 22.04 / Docker Container
Requirements: Python 3.10+, gRPC, Kafka, MongoDB, Redis
"""

# ============================================================================
# PARTE 1: CONFIGURAÇÕES E IMPORTS
# ============================================================================

import os
import sys
import json
import uuid
import asyncio
import logging
import hashlib
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from functools import wraps
from dataclasses import dataclass, asdict

# gRPC
import grpc
from grpc import aio
from concurrent import futures

# Kafka
from kafka import KafkaProducer, KafkaConsumer
from kafka.errors import KafkaError

# MongoDB
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

# WebSocket
import websockets
from websockets.server import WebSocketServerProtocol

# JWT & Auth
import jwt
import secrets
from passlib.context import CryptContext

# Utilities
import click
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================================================================
# CONFIGURAÇÕES
# ============================================================================

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment Variables
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017')
KAFKA_BROKERS = os.getenv('KAFKA_BROKERS', 'localhost:9092').split(',')
WEBSOCKET_HOST = os.getenv('WEBSOCKET_HOST', '0.0.0.0')
WEBSOCKET_PORT = int(os.getenv('WEBSOCKET_PORT', '8765'))
GRPC_HOST = os.getenv('GRPC_HOST', '0.0.0.0')
GRPC_PORT = int(os.getenv('GRPC_PORT', '50051'))
JWT_SECRET = os.getenv('JWT_SECRET', 'your-secret-key-change-in-production')
JWT_ALGORITHM = 'HS256'
JWT_EXPIRY_HOURS = 1

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ============================================================================
# PART 2: DATA MODELS
# ============================================================================

@dataclass
class User:
    id: str
    username: str
    full_name: str
    email: str
    password_hash: str
    is_active: bool = True
    is_staff: bool = False
    created_at: int = None
    updated_at: int = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = int(datetime.now().timestamp())
        if self.updated_at is None:
            self.updated_at = int(datetime.now().timestamp())

    def to_dict(self, include_password=False):
        d = asdict(self)
        if not include_password:
            d.pop('password_hash', None)
        return d

@dataclass
class Message:
    id: str
    conversation_id: str
    sender_id: str
    sequence_number: int
    message_type: str
    payload_text: str
    channels_requested: List[str]
    file_metadata_id: str = None
    sent_at: int = None
    metadata: Dict = None

    def __post_init__(self):
        if self.sent_at is None:
            self.sent_at = int(datetime.now().timestamp())
        if self.metadata is None:
            self.metadata = {}

@dataclass
class Conversation:
    id: str
    type: str  # "private" or "group"
    name: str
    created_by_id: str
    member_ids: List[str]
    created_at: int = None
    updated_at: int = None
    metadata: Dict = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = int(datetime.now().timestamp())
        if self.updated_at is None:
            self.updated_at = int(datetime.now().timestamp())
        if self.metadata is None:
            self.metadata = {}

# ============================================================================
# PART 3: DATABASE LAYER - MONGODB
# ============================================================================

class MongoDBConnector:
    """MongoDB connection and operations"""
    
    def __init__(self, uri: str):
        self.client = MongoClient(uri)
        self.db = self.client['chat4all']
        self._init_collections()
        logger.info("MongoDB connected successfully")
    
    def _init_collections(self):
        """Initialize collections with indexes"""
        # Users collection
        if 'users' not in self.db.list_collection_names():
            self.db.create_collection('users')
        self.db.users.create_index([('username', ASCENDING)], unique=True)
        self.db.users.create_index([('email', ASCENDING)], unique=True)
        
        # Conversations collection
        if 'conversations' not in self.db.list_collection_names():
            self.db.create_collection('conversations')
        self.db.conversations.create_index([('created_at', DESCENDING)])
        self.db.conversations.create_index([('type', ASCENDING)])
        
        # Messages collection
        if 'messages' not in self.db.list_collection_names():
            self.db.create_collection('messages')
        self.db.messages.create_index([('conversation_id', ASCENDING), ('sequence_number', ASCENDING)], unique=True)
        self.db.messages.create_index([('sender_id', ASCENDING), ('sent_at', DESCENDING)])
        self.db.messages.create_index([('sent_at', DESCENDING)])
        
        # Message Status collection
        if 'message_status' not in self.db.list_collection_names():
            self.db.create_collection('message_status')
        self.db.message_status.create_index([('message_id', ASCENDING), ('recipient_id', ASCENDING), ('channel_type', ASCENDING)])
        self.db.message_status.create_index([('status', ASCENDING), ('status_timestamp', DESCENDING)])
        
        # Conversation Members
        if 'conversation_members' not in self.db.list_collection_names():
            self.db.create_collection('conversation_members')
        self.db.conversation_members.create_index([('conversation_id', ASCENDING), ('user_id', ASCENDING)], unique=True)
        self.db.conversation_members.create_index([('user_id', ASCENDING)])
        
        logger.info("MongoDB collections initialized")
    
    # User operations
    def create_user(self, user: User) -> bool:
        try:
            self.db.users.insert_one(asdict(user))
            logger.info(f"User created: {user.username}")
            return True
        except DuplicateKeyError:
            logger.warning(f"User already exists: {user.username}")
            return False
    
    def get_user_by_username(self, username: str) -> Optional[User]:
        doc = self.db.users.find_one({'username': username})
        if doc:
            doc.pop('_id')
            return User(**doc)
        return None
    
    def get_user_by_id(self, user_id: str) -> Optional[User]:
        doc = self.db.users.find_one({'id': user_id})
        if doc:
            doc.pop('_id')
            return User(**doc)
        return None
    
    # Message operations
    def save_message(self, message: Message) -> bool:
        try:
            self.db.messages.insert_one(asdict(message))
            logger.info(f"Message saved: {message.id}")
            return True
        except Exception as e:
            logger.error(f"Error saving message: {e}")
            return False
    
    def get_message(self, message_id: str) -> Optional[Message]:
        doc = self.db.messages.find_one({'id': message_id})
        if doc:
            doc.pop('_id')
            return Message(**doc)
        return None
    
    def get_conversation_messages(self, conversation_id: str, limit: int = 50, offset: int = 0) -> List[Message]:
        messages = list(self.db.messages.find(
            {'conversation_id': conversation_id}
        ).sort('sequence_number', DESCENDING).skip(offset).limit(limit))
        
        result = []
        for doc in messages:
            doc.pop('_id')
            result.append(Message(**doc))
        return result
    
    # Conversation operations
    def create_conversation(self, conversation: Conversation) -> bool:
        try:
            self.db.conversations.insert_one(asdict(conversation))
            logger.info(f"Conversation created: {conversation.id}")
            return True
        except Exception as e:
            logger.error(f"Error creating conversation: {e}")
            return False
    
    def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        doc = self.db.conversations.find_one({'id': conversation_id})
        if doc:
            doc.pop('_id')
            return Conversation(**doc)
        return None
    
    def save_message_status(self, message_id: str, recipient_id: str, channel_type: str, status: str, timestamp: int = None):
        if timestamp is None:
            timestamp = int(datetime.now().timestamp())
        
        status_doc = {
            'id': str(uuid.uuid4()),
            'message_id': message_id,
            'recipient_id': recipient_id,
            'channel_type': channel_type,
            'status': status,
            'status_timestamp': timestamp
        }
        
        self.db.message_status.insert_one(status_doc)
        logger.info(f"Message status saved: {message_id} -> {status}")
    
    def get_message_status(self, message_id: str) -> List[Dict]:
        statuses = list(self.db.message_status.find({'message_id': message_id}))
        for status in statuses:
            status.pop('_id')
        return statuses

# ============================================================================
# PART 4: KAFKA PRODUCER & CONSUMER
# ============================================================================

class KafkaService:
    """Kafka message broker service"""
    
    def __init__(self, brokers: List[str]):
        self.brokers = brokers
        self.producer = KafkaProducer(
            bootstrap_servers=brokers,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            acks='all',  # Wait for all replicas
            retries=3
        )
        logger.info(f"Kafka producer initialized: {brokers}")
    
    def send_message_event(self, message: Message) -> bool:
        """Publish message event to Kafka for async processing"""
        try:
            event = {
                'event_type': 'message_sent',
                'message_id': message.id,
                'conversation_id': message.conversation_id,
                'sender_id': message.sender_id,
                'channels_requested': message.channels_requested,
                'timestamp': int(datetime.now().timestamp())
            }
            
            # Partition by conversation_id to preserve order
            future = self.producer.send(
                'chat4all.messages',
                value=event,
                key=message.conversation_id.encode('utf-8')
            )
            
            future.get(timeout=10)  # Wait for confirmation
            logger.info(f"Message event published to Kafka: {message.id}")
            return True
        except Exception as e:
            logger.error(f"Error publishing message to Kafka: {e}")
            return False
    
    def send_status_update(self, message_id: str, recipient_id: str, channel: str, status: str):
        """Publish status update event"""
        try:
            event = {
                'event_type': 'status_update',
                'message_id': message_id,
                'recipient_id': recipient_id,
                'channel': channel,
                'status': status,
                'timestamp': int(datetime.now().timestamp())
            }
            
            self.producer.send(
                'chat4all.status_updates',
                value=event,
                key=message_id.encode('utf-8')
            )
            logger.info(f"Status update published: {message_id} -> {status}")
        except Exception as e:
            logger.error(f"Error publishing status update: {e}")
    
    def flush(self):
        """Flush producer"""
        self.producer.flush()

class KafkaWorker:
    """Kafka consumer for processing messages"""
    
    def __init__(self, brokers: List[str], db: MongoDBConnector, kafka_service: KafkaService):
        self.brokers = brokers
        self.db = db
        self.kafka_service = kafka_service
        self.consumer = KafkaConsumer(
            'chat4all.messages',
            bootstrap_servers=brokers,
            group_id='chat4all-workers',
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            auto_offset_reset='earliest',
            enable_auto_commit=True,
            max_poll_records=100
        )
        logger.info(f"Kafka consumer initialized: {brokers}")
    
    async def start_consuming(self):
        """Start consuming messages from Kafka"""
        logger.info("Starting Kafka worker...")
        
        try:
            for message in self.consumer:
                event = message.value
                logger.info(f"Processing message event: {event['message_id']}")
                
                # Process message and route to connectors
                await self._process_message_event(event)
        except Exception as e:
            logger.error(f"Error in Kafka worker: {e}")
    
    async def _process_message_event(self, event: Dict):
        """Process a message event and route to connectors"""
        message_id = event['message_id']
        channels = event['channels_requested']
        
        # Simulate connector calls (in production, these would be real API calls)
        for channel in channels:
            logger.info(f"Routing message {message_id} to channel: {channel}")
            
            # Update status: SENT -> DELIVERED
            await asyncio.sleep(0.5)  # Simulate processing
            self.kafka_service.send_status_update(message_id, event.get('recipient_id', ''), channel, 'DELIVERED')
            
            # Simulate READ status after 2 seconds
            await asyncio.sleep(1.5)
            self.kafka_service.send_status_update(message_id, event.get('recipient_id', ''), channel, 'READ')

# ============================================================================
# PART 5: AUTHENTICATION
# ============================================================================

def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password"""
    return pwd_context.verify(plain_password, hashed_password)

def create_jwt_token(user_id: str, username: str) -> str:
    """Create JWT token"""
    payload = {
        'user_id': user_id,
        'username': username,
        'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
        'iat': datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_jwt_token(token: str) -> Optional[Dict]:
    """Verify and decode JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token expired")
        return None
    except jwt.InvalidTokenError:
        logger.warning("Invalid JWT token")
        return None

# ============================================================================
# PART 6: WEBSOCKET SERVER
# ============================================================================

class WebSocketManager:
    """Manage WebSocket connections for real-time messaging"""
    
    def __init__(self):
        self.connections: Dict[str, WebSocketServerProtocol] = {}
        self.user_connections: Dict[str, List[str]] = {}  # user_id -> connection_ids
    
    async def register(self, connection: WebSocketServerProtocol, user_id: str):
        """Register a new WebSocket connection"""
        conn_id = str(uuid.uuid4())
        self.connections[conn_id] = connection
        
        if user_id not in self.user_connections:
            self.user_connections[user_id] = []
        self.user_connections[user_id].append(conn_id)
        
        logger.info(f"WebSocket registered: {user_id} ({conn_id})")
        return conn_id
    
    async def unregister(self, conn_id: str):
        """Unregister a WebSocket connection"""
        if conn_id in self.connections:
            del self.connections[conn_id]
            # Remove from user_connections
            for user_id, conns in self.user_connections.items():
                if conn_id in conns:
                    conns.remove(conn_id)
                    logger.info(f"WebSocket unregistered: {user_id} ({conn_id})")
    
    async def send_to_user(self, user_id: str, message: Dict):
        """Send message to specific user"""
        if user_id not in self.user_connections:
            return
        
        for conn_id in self.user_connections[user_id]:
            try:
                if conn_id in self.connections:
                    await self.connections[conn_id].send(json.dumps(message))
            except websockets.exceptions.ConnectionClosed:
                await self.unregister(conn_id)
    
    async def broadcast(self, message: Dict, exclude_user: str = None):
        """Broadcast message to all connected users"""
        for conn_id, connection in list(self.connections.items()):
            try:
                await connection.send(json.dumps(message))
            except websockets.exceptions.ConnectionClosed:
                await self.unregister(conn_id)

ws_manager = WebSocketManager()

# ============================================================================
# PART 7: WEBSOCKET HANDLER
# ============================================================================

async def websocket_handler(websocket: WebSocketServerProtocol, path: str):
    """WebSocket connection handler"""
    conn_id = None
    user_id = None
    
    try:
        # First message should be authentication
        auth_message = await websocket.recv()
        auth_data = json.loads(auth_message)
        
        token = auth_data.get('token')
        if not token:
            await websocket.send(json.dumps({'type': 'error', 'message': 'Authentication required'}))
            return
        
        # Verify token
        payload = verify_jwt_token(token)
        if not payload:
            await websocket.send(json.dumps({'type': 'error', 'message': 'Invalid token'}))
            return
        
        user_id = payload.get('user_id')
        conn_id = await ws_manager.register(websocket, user_id)
        
        # Send confirmation
        await websocket.send(json.dumps({
            'type': 'connected',
            'connection_id': conn_id,
            'user_id': user_id
        }))
        
        # Listen for messages
        async for message in websocket:
            try:
                data = json.loads(message)
                await _handle_websocket_message(data, user_id)
            except json.JSONDecodeError:
                await websocket.send(json.dumps({'type': 'error', 'message': 'Invalid JSON'}))
    
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"WebSocket connection closed: {user_id}")
    
    finally:
        if conn_id:
            await ws_manager.unregister(conn_id)

async def _handle_websocket_message(data: Dict, user_id: str):
    """Handle incoming WebSocket message"""
    message_type = data.get('type')
    
    if message_type == 'message_received':
        # Broadcast to conversation members
        conversation_id = data.get('conversation_id')
        logger.info(f"Message received: {conversation_id} from {user_id}")
        
        # Notify other users
        await ws_manager.send_to_user(data.get('recipient_id'), {
            'type': 'new_message',
            'message': data
        })
    
    elif message_type == 'typing':
        # Broadcast typing indicator
        conversation_id = data.get('conversation_id')
        await ws_manager.broadcast({
            'type': 'user_typing',
            'conversation_id': conversation_id,
            'user_id': user_id
        }, exclude_user=user_id)
    
    elif message_type == 'presence':
        # Update presence
        is_online = data.get('is_online')
        logger.info(f"User presence update: {user_id} -> {is_online}")
        
        await ws_manager.broadcast({
            'type': 'presence_update',
            'user_id': user_id,
            'is_online': is_online
        })

# ============================================================================
# PART 8: GRPC SERVICE IMPLEMENTATION
# ============================================================================

# Import generated protobuf (in real implementation, these would be generated)
# For now, we'll create a mock implementation

class Chat4AllServicer:
    """gRPC Chat4All Service implementation"""
    
    def __init__(self, db: MongoDBConnector, kafka_service: KafkaService):
        self.db = db
        self.kafka = kafka_service
    
    # Authentication methods
    async def Authenticate(self, request, context):
        """Authenticate user and return JWT token"""
        username = request.username
        password = request.password
        
        user = self.db.get_user_by_username(username)
        if not user or not verify_password(password, user.password_hash):
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid credentials")
        
        access_token = create_jwt_token(user.id, user.username)
        
        # In production, also generate refresh token
        return {
            'access_token': access_token,
            'refresh_token': access_token,  # Simplified
            'expires_in': JWT_EXPIRY_HOURS * 3600
        }
    
    async def Register(self, request, context):
        """Register new user"""
        username = request.username
        password = request.password
        full_name = request.full_name
        email = request.email
        
        # Check if user already exists
        if self.db.get_user_by_username(username):
            await context.abort(grpc.StatusCode.ALREADY_EXISTS, "User already exists")
        
        user = User(
            id=str(uuid.uuid4()),
            username=username,
            full_name=full_name,
            email=email,
            password_hash=hash_password(password)
        )
        
        if not self.db.create_user(user):
            await context.abort(grpc.StatusCode.INTERNAL, "Failed to create user")
        
        return {
            'user_id': user.id,
            'username': user.username,
            'message': 'User registered successfully'
        }
    
    async def SendMessage(self, request, context):
        try:
            message_id = str(uuid.uuid4())
        
        # Validar autenticação
        metadata = dict(context.invocation_metadata())
        token = metadata.get('authorization', '').replace('Bearer ', '')
        user_id = await self.auth_service.verify_token(token)
        
        # Preparar payload
        payload = {
            'id': message_id,
            'conversation_id': request.conversation_id,
            'sender_id': user_id,
            'type': request.type.name if request.type else 'TEXT',
            'channels': request.channels,
            'created_at': datetime.utcnow().isoformat()
        }
        
        if request.type == MessageType.TEXT:
            payload['text'] = request.text
        elif request.type in [MessageType.FILE, MessageType.IMAGE, MessageType.VIDEO]:
            payload['file_id'] = request.file_id
            payload['file_metadata'] = {
                'filename': request.file_metadata.filename,
                'mime_type': request.file_metadata.mime_type,
                'file_size': request.file_metadata.file_size,
                'checksum': request.file_metadata.checksum
            }
        
        # Publicar em Kafka
        await self.kafka_service.send_message_event(payload)
        
        # Salvar status
        await self.db.save_message_status(
            message_id, 'SENT', user_id
        )
        
        return SendMessageResponse(
            message_id=message_id,
            status='SENT',
            timestamp=int(datetime.utcnow().timestamp() * 1000)
        )
    except Exception as e:
        logger.error(f"Error in SendMessage: {e}")
        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))

    
    async def GetMessage(self, request, context):
        """Get message by ID"""
        message = self.db.get_message(request.message_id)
        if not message:
            await context.abort(grpc.StatusCode.NOT_FOUND, "Message not found")
        
        return asdict(message)
    
    async def GetMessageStatus(self, request, context):
        """Get message delivery status"""
        statuses = self.db.get_message_status(request.message_id)
        return {'statuses': statuses}
    
    async def ListMessages(self, request, context):
        """List messages in conversation"""
        limit = request.page_size if request.page_size > 0 else 50
        offset = (request.page - 1) * limit if request.page > 0 else 0
        
        messages = self.db.get_conversation_messages(request.conversation_id, limit, offset)
        
        return {
            'count': len(messages),
            'messages': [asdict(msg) for msg in messages],
            'has_next': len(messages) == limit
        }

# ============================================================================
# PART 9: MAIN SERVER
# ============================================================================

async def serve_grpc(servicer, host: str, port: int):
    """Start gRPC server"""
    server = grpc.aio.server()
    # Add servicer to server (in real implementation, use generated code)
    logger.info(f"gRPC server starting on {host}:{port}")
    
    await server.start()
    await server.wait_for_termination()

async def serve_websocket(host: str, port: int):
    """Start WebSocket server"""
    async with websockets.serve(websocket_handler, host, port):
        logger.info(f"WebSocket server started on {host}:{port}")
        await asyncio.Future()  # Run forever

async def main():
    """Start all services"""
    # Initialize components
    db = MongoDBConnector(MONGO_URI)
    kafka_service = KafkaService(KAFKA_BROKERS)
    servicer = Chat4AllServicer(db, kafka_service)
    worker = KafkaWorker(KAFKA_BROKERS, db, kafka_service)
    
    # Create tasks for all services
    tasks = [
        serve_grpc(servicer, GRPC_HOST, GRPC_PORT),
        serve_websocket(WEBSOCKET_HOST, WEBSOCKET_PORT),
        worker.start_consuming()
    ]
    
    # Run all services concurrently
    await asyncio.gather(*tasks)

if __name__ == '__main__':
    logger.info("Chat4All v2 Backend Server Starting...")
    asyncio.run(main())
