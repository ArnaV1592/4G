"""
MongoDB database configuration and connection management
"""

import motor.motor_asyncio
from pymongo import MongoClient
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class MongoDB:
    """MongoDB connection and collection management"""
    
    def __init__(self, connection_string: str, database_name: str = "iwown_health"):
        self.connection_string = connection_string
        self.database_name = database_name
        self.client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None
        self.database: Optional[motor.motor_asyncio.AsyncIOMotorDatabase] = None
        
        # Collection names
        self.collections = {
            'health_data': 'health_data',
            'alarms': 'alarms',
            'sos_calls': 'sos_calls',
            'device_info': 'device_info',
            'status': 'status',
            'sleep_data': 'sleep_data'
        }
    
    async def connect(self):
        """Establish connection to MongoDB"""
        try:
            # Simple MongoDB Atlas connection with minimal SSL settings
            connection_kwargs = {
                "serverSelectionTimeoutMS": 30000,
                "connectTimeoutMS": 30000,
                "socketTimeoutMS": 30000,
                "maxPoolSize": 10,
                "minPoolSize": 1,
                "maxIdleTimeMS": 30000
            }
            
            self.client = motor.motor_asyncio.AsyncIOMotorClient(
                self.connection_string, 
                **connection_kwargs
            )
            self.database = self.client[self.database_name]
            
            # Test connection
            await self.client.admin.command('ping')
            logger.info(f"Connected to MongoDB database: {self.database_name}")
            
            # Create indexes for better performance
            await self._create_indexes()
            
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            # Try alternative connection method
            await self._try_alternative_connection()
    
    async def _try_alternative_connection(self):
        """Try connecting with different SSL settings"""
        try:
            logger.info("Trying alternative connection method...")
            
            # Simpler connection without explicit SSL context
            connection_kwargs = {
                "serverSelectionTimeoutMS": 30000,
                "connectTimeoutMS": 30000,
                "socketTimeoutMS": 30000,
                "maxPoolSize": 10,
                "minPoolSize": 1,
                "maxIdleTimeMS": 30000
            }
            
            # Create connection string without SSL parameters for this attempt
            base_connection = self.connection_string.split('?')[0]
            alt_connection_string = f"{base_connection}?retryWrites=true&w=majority"
            
            self.client = motor.motor_asyncio.AsyncIOMotorClient(
                alt_connection_string, 
                **connection_kwargs
            )
            self.database = self.client[self.database_name]
            
            # Test connection
            await self.client.admin.command('ping')
            logger.info(f"Alternative connection successful to database: {self.database_name}")
            
            # Create indexes for better performance
            await self._create_indexes()
            
        except Exception as e:
            logger.error(f"Alternative connection also failed: {e}")
            raise
    
    async def disconnect(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            logger.info("Disconnected from MongoDB")
    
    async def _create_indexes(self):
        """Create database indexes for better performance"""
        try:
            # Health data indexes
            await self.database[self.collections['health_data']].create_index([
                ("device_id", 1),
                ("timestamp", -1)
            ])
            
            # Alarm indexes
            await self.database[self.collections['alarms']].create_index([
                ("device_id", 1),
                ("timestamp", -1)
            ])
            
            # SOS calls indexes
            await self.database[self.collections['sos_calls']].create_index([
                ("device_id", 1),
                ("timestamp", -1)
            ])
            
            # Device info indexes
            await self.database[self.collections['device_info']].create_index([
                ("device_id", 1)
            ], unique=True)
            
            # Status indexes
            await self.database[self.collections['status']].create_index([
                ("device_id", 1)
            ], unique=True)
            
            # Sleep data indexes
            await self.database[self.collections['sleep_data']].create_index([
                ("device_id", 1),
                ("sleep_date", -1)
            ])
            
            logger.info("Database indexes created successfully")
            
        except Exception as e:
            logger.error(f"Failed to create indexes: {e}")
    
    def get_collection(self, collection_name: str):
        """Get a specific collection"""
        if self.database is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        
        if collection_name not in self.collections:
            raise ValueError(f"Unknown collection: {collection_name}")
        
        return self.database[self.collections[collection_name]]

# Global database instance
mongodb: Optional[MongoDB] = None

async def get_database() -> MongoDB:
    """Get the global database instance"""
    if not mongodb:
        raise RuntimeError("Database not initialized")
    return mongodb

async def init_database(connection_string: str, database_name: str = "iwown_health"):
    """Initialize the global database instance"""
    global mongodb
    mongodb = MongoDB(connection_string, database_name)
    await mongodb.connect()
    return mongodb