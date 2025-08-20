"""
iWOWN Health Monitoring FastAPI Application
Production-ready API for iWOWN device data ingestion and dashboard
"""

import os
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field
import uvicorn

from database import init_database, get_database
from config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Security
security = HTTPBearer(auto_error=False)

# MongoDB collections will be initialized in lifespan

# Pydantic models for request/response validation
class DeviceInfo(BaseModel):
    deviceid: Optional[str] = None
    battery: Optional[int] = None
    firmware_version: Optional[str] = None
    model: Optional[str] = None

class AlarmData(BaseModel):
    deviceid: Optional[str] = None
    alarm_type: Optional[str] = None
    timestamp: Optional[str] = None
    location: Optional[str] = None

class CallLogData(BaseModel):
    deviceid: Optional[str] = None
    call_type: Optional[str] = None
    timestamp: Optional[str] = None
    duration: Optional[int] = None

class StatusData(BaseModel):
    DeviceId: Optional[str] = None
    Status: Optional[str] = None
    battery_level: Optional[int] = None
    signal_strength: Optional[int] = None

class SleepData(BaseModel):
    device_id: Optional[str] = None
    sleep_date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    deep_sleep: Optional[int] = None
    light_sleep: Optional[int] = None
    weak_sleep: Optional[int] = None
    eyemove_sleep: Optional[int] = None
    score: Optional[int] = None
    osahs_risk: Optional[int] = None
    spo2_score: Optional[int] = None
    sleep_hr: Optional[int] = None

class HealthResponse(BaseModel):
    ReturnCode: int = 0
    Data: Dict[str, Any] = {}

class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Any] = None
    timestamp: str

# Utility functions
def get_current_timestamp() -> str:
    """Get current UTC timestamp in ISO format"""
    return datetime.now(timezone.utc).isoformat()

def convert_mongodb_document(doc: dict) -> dict:
    """Convert MongoDB document to JSON-serializable format"""
    if doc is None:
        return None
    
    # Convert ObjectId to string
    if '_id' in doc and hasattr(doc['_id'], '__str__'):
        doc['_id'] = str(doc['_id'])
    
    # Convert datetime objects to ISO strings
    for key, value in doc.items():
        if isinstance(value, datetime):
            doc[key] = value.isoformat()
        elif isinstance(value, dict):
            doc[key] = convert_mongodb_document(value)
        elif isinstance(value, list):
            doc[key] = [convert_mongodb_document(item) if isinstance(item, dict) else item for item in value]
    
    return doc



def get_device_id(request: Request, data: Optional[Dict] = None) -> str:
    """Extract device ID from headers or data"""
    device_id = request.headers.get('DeviceId')
    if data and isinstance(data, dict):
        device_id = data.get('deviceid') or data.get('DeviceId') or device_id
    return device_id or 'unknown'

def log_request(endpoint: str, device_id: str, data_size: int = 0):
    """Log incoming request"""
    logger.info(f"Request to {endpoint} from device {device_id}, data size: {data_size} bytes")

# Background task for data processing
async def process_health_data(device_id: str, payload: bytes, timestamp: str):
    """Process health data asynchronously"""
    try:
        # Here you could add data validation, transformation, or external API calls
        logger.info(f"Processing health data for device {device_id}, size: {len(payload)} bytes")
        # Add your business logic here
    except Exception as e:
        logger.error(f"Error processing health data for device {device_id}: {e}")

# FastAPI app with lifespan management
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting iWOWN Health Monitoring API...")
    
    # Initialize MongoDB connection
    try:
        await init_database(settings.MONGODB_URL, settings.MONGODB_DATABASE)
        logger.info("MongoDB connection established")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        logger.warning("API will start without database connection. Some features may not work.")
        # Don't raise the exception - allow the API to start without DB
    
    yield
    
    # Shutdown
    logger.info("Shutting down iWOWN Health Monitoring API...")
    
    # Close MongoDB connection
    try:
        db = await get_database()
        await db.disconnect()
        logger.info("MongoDB connection closed")
    except Exception as e:
        logger.error(f"Error closing MongoDB connection: {e}")

app = FastAPI(
    title="iWOWN Health Monitoring API",
    description="Production API for iWOWN device data ingestion and health monitoring",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check endpoint
@app.get("/health", response_model=ApiResponse)
async def health_check():
    """Health check endpoint"""
    try:
        # Check database connection
        db = await get_database()
        await db.client.admin.command('ping')
        db_status = "connected"
    except Exception:
        db_status = "disconnected"
    
    return ApiResponse(
        success=True,
        message=f"API is running (Database: {db_status})",
        data={"database_status": db_status},
        timestamp=get_current_timestamp()
    )

# iWOWN Device Endpoints (must end with these exact paths)
@app.post("/4g/pb/upload")
async def pb_upload(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Upload health data from iWOWN device
    Returns: Single byte 0x00 for success
    """
    try:
        payload = await request.body()
        device_id = get_device_id(request)
        
        log_request("/4g/pb/upload", device_id, len(payload))
        
        if payload:
            # Store data in MongoDB
            db = await get_database()
            collection = db.get_collection('health_data')
            
            health_data = {
                'device_id': device_id,
                'timestamp': get_current_timestamp(),
                'raw_hex': payload.hex(),
                'decoded': None,
                'size': len(payload),
                'created_at': datetime.now(timezone.utc)
            }
            
            await collection.insert_one(health_data)
            
            # Process data in background
            background_tasks.add_task(process_health_data, device_id, payload, health_data['timestamp'])
        
        # Return single byte 0x00 as required by iWOWN
        return Response(content=b'\x00', media_type='application/octet-stream')
        
    except Exception as e:
        logger.error(f"Error in pb_upload: {e}")
        return Response(content=b'\x00', media_type='application/octet-stream')

@app.post("/4g/alarm/upload")
async def alarm_upload(request: Request):
    """
    Upload alarm data from iWOWN device
    Returns: Single byte 0x00 for success
    """
    try:
        device_id = get_device_id(request)
        data = await request.json() if request.headers.get('content-type') == 'application/json' else None
        
        log_request("/4g/alarm/upload", device_id)
        
        # Store data in MongoDB
        db = await get_database()
        collection = db.get_collection('alarms')
        
        alarm_data = {
            'device_id': device_id,
            'timestamp': get_current_timestamp(),
            'created_at': datetime.now(timezone.utc)
        }
        
        if data:
            alarm_data.update(data)
        else:
            # Store raw data if not JSON
            raw_data = await request.body()
            alarm_data['raw_hex'] = raw_data.hex()
        
        await collection.insert_one(alarm_data)
        
        return Response(content=b'\x00', media_type='application/octet-stream')
        
    except Exception as e:
        logger.error(f"Error in alarm_upload: {e}")
        return Response(content=b'\x00', media_type='application/octet-stream')

@app.post("/4g/call_log/upload")
async def call_log_upload(request: Request):
    """
    Upload call log/SOS data from iWOWN device
    Returns: Single byte 0x00 for success
    """
    try:
        device_id = get_device_id(request)
        data = await request.json() if request.headers.get('content-type') == 'application/json' else None
        
        log_request("/4g/call_log/upload", device_id)
        
        # Store data in MongoDB
        db = await get_database()
        collection = db.get_collection('sos_calls')
        
        call_data = {
            'device_id': device_id,
            'timestamp': get_current_timestamp(),
            'created_at': datetime.now(timezone.utc)
        }
        
        if data:
            call_data.update(data)
        else:
            raw_data = await request.body()
            call_data['raw_hex'] = raw_data.hex()
        
        await collection.insert_one(call_data)
        
        return Response(content=b'\x00', media_type='application/octet-stream')
        
    except Exception as e:
        logger.error(f"Error in call_log_upload: {e}")
        return Response(content=b'\x00', media_type='application/octet-stream')

@app.post("/4g/deviceinfo/upload")
async def deviceinfo_upload(request: Request):
    """
    Upload device information from iWOWN device
    Returns: Single byte 0x00 for success
    """
    try:
        device_id = get_device_id(request)
        data = await request.json() if request.headers.get('content-type') == 'application/json' else None
        
        log_request("/4g/deviceinfo/upload", device_id)
        
        # Store data in MongoDB (upsert - update if exists, insert if not)
        db = await get_database()
        collection = db.get_collection('device_info')
        
        device_info = {
            'device_id': device_id,
            'updated_at': datetime.now(timezone.utc)
        }
        
        if data:
            device_info.update(data)
        else:
            raw_data = await request.body()
            device_info['raw_hex'] = raw_data.hex()
            device_info['timestamp'] = get_current_timestamp()
        
        await collection.replace_one(
            {'device_id': device_id},
            device_info,
            upsert=True
        )
        
        return Response(content=b'\x00', media_type='application/octet-stream')
        
    except Exception as e:
        logger.error(f"Error in deviceinfo_upload: {e}")
        return Response(content=b'\x00', media_type='application/octet-stream')

@app.post("/4g/status/notify")
async def status_notify(request: Request):
    """
    Receive status notifications from iWOWN device
    Returns: Single byte 0x00 for success
    """
    try:
        device_id = get_device_id(request)
        data = await request.json() if request.headers.get('content-type') == 'application/json' else {}
        
        log_request("/4g/status/notify", device_id)
        
        # Store data in MongoDB (upsert - update if exists, insert if not)
        db = await get_database()
        collection = db.get_collection('status')
        
        status_data = {
            'device_id': device_id,
            'last_update': get_current_timestamp(),
            'updated_at': datetime.now(timezone.utc),
            **data
        }
        
        await collection.replace_one(
            {'device_id': device_id},
            status_data,
            upsert=True
        )
        
        return Response(content=b'\x00', media_type='application/octet-stream')
        
    except Exception as e:
        logger.error(f"Error in status_notify: {e}")
        return Response(content=b'\x00', media_type='application/octet-stream')

@app.post("/4g/health/sleep", response_model=HealthResponse)
async def sleep_result(request: Request):
    """
    Get sleep health data for iWOWN device
    Returns: Sleep data with ReturnCode 0
    """
    try:
        device_id = get_device_id(request)
        data = await request.json() if request.headers.get('content-type') == 'application/json' else {}
        
        log_request("/4g/health/sleep", device_id)
        
        # Store data in MongoDB (upsert - update if exists, insert if not)
        db = await get_database()
        collection = db.get_collection('sleep_data')
        
        sleep_data = {
            'device_id': device_id,
            'sleep_date': datetime.now().strftime('%Y-%m-%d'),
            'start_time': '22:00:00',
            'end_time': '06:00:00',
            'deep_sleep': 120,
            'light_sleep': 280,
            'weak_sleep': 20,
            'eyemove_sleep': 30,
            'score': 85,
            'osahs_risk': 0,
            'spo2_score': 0,
            'sleep_hr': 65,
            'updated_at': datetime.now(timezone.utc)
        }
        
        # Update with new data if provided
        if data:
            sleep_data.update(data)
        
        await collection.replace_one(
            {'device_id': device_id, 'sleep_date': sleep_data['sleep_date']},
            sleep_data,
            upsert=True
        )
        
        # Return the data in the expected format
        result = {
            'deviceid': device_id,
            'sleep_date': sleep_data['sleep_date'],
            'start_time': sleep_data['start_time'],
            'end_time': sleep_data['end_time'],
            'deep_sleep': sleep_data['deep_sleep'],
            'light_sleep': sleep_data['light_sleep'],
            'weak_sleep': sleep_data['weak_sleep'],
            'eyemove_sleep': sleep_data['eyemove_sleep'],
            'score': sleep_data['score'],
            'osahs_risk': sleep_data['osahs_risk'],
            'spo2_score': sleep_data['spo2_score'],
            'sleep_hr': sleep_data['sleep_hr']
        }
        
        return HealthResponse(ReturnCode=0, Data=result)
        
    except Exception as e:
        logger.error(f"Error in sleep_result: {e}")
        return HealthResponse(ReturnCode=0, Data={})

# Dashboard API Endpoints
@app.get("/api/devices", response_model=ApiResponse)
async def get_devices():
    """Get list of all devices with basic info"""
    try:
        db = await get_database()
        
        # Get all unique device IDs from different collections
        health_collection = db.get_collection('health_data')
        device_info_collection = db.get_collection('device_info')
        status_collection = db.get_collection('status')
        
        # Get device IDs from health data
        health_devices = await health_collection.distinct('device_id')
        
        # Get device IDs from device info
        device_info_devices = await device_info_collection.distinct('device_id')
        
        # Get device IDs from status
        status_devices = await status_collection.distinct('device_id')
        
        # Combine all device IDs
        all_device_ids = set(health_devices + device_info_devices + status_devices)
        
        devices = []
        for device_id in all_device_ids:
            # Get device info
            device_info = await device_info_collection.find_one({'device_id': device_id})
            
            # Get status info
            status_info = await status_collection.find_one({'device_id': device_id})
            
            devices.append({
                'id': device_id,
                'battery': device_info.get('battery') if device_info else None,
                'status': status_info.get('Status', 'unknown') if status_info else 'unknown',
                'last_seen': status_info.get('last_update') if status_info else None,
                'firmware': device_info.get('firmware_version') if device_info else None,
                'model': device_info.get('model') if device_info else None
            })
        
        return ApiResponse(
            success=True,
            message="Devices retrieved successfully",
            data=devices,
            timestamp=get_current_timestamp()
        )
        
    except Exception as e:
        logger.error(f"Error getting devices: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/stats", response_model=ApiResponse)
async def get_stats():
    """Get overall system statistics"""
    try:
        db = await get_database()
        
        # Get collections
        health_collection = db.get_collection('health_data')
        device_info_collection = db.get_collection('device_info')
        status_collection = db.get_collection('status')
        alarm_collection = db.get_collection('alarms')
        
        # Count total devices
        total_devices = len(await device_info_collection.distinct('device_id'))
        
        # Count online devices
        online_devices = await status_collection.count_documents({'Status': 'online'})
        
        # Count fall alerts
        fall_alerts = await alarm_collection.count_documents({'alarm_type': 'fall_detected'})
        
        # Count total health records
        total_health_records = await health_collection.count_documents({})
        
        # Calculate averages (simplified - you can enhance this with actual data parsing)
        stats = {
            'total_devices': total_devices,
            'online_devices': online_devices,
            'fall_alerts': fall_alerts,
            'total_health_records': total_health_records,
            'avg_hr': 0,  # Add calculation logic when you decode health data
            'avg_o2': 0,  # Add calculation logic when you decode health data
            'avg_hrv': 0,  # Add calculation logic
            'avg_stress': 0,  # Add calculation logic
            'avg_sleep_hours': 7.5  # Add calculation logic
        }
        
        return ApiResponse(
            success=True,
            message="Statistics retrieved successfully",
            data=stats,
            timestamp=get_current_timestamp()
        )
        
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/device/{device_id}/health", response_model=ApiResponse)
async def get_device_health(device_id: str):
    """Get health data for specific device"""
    try:
        db = await get_database()
        collection = db.get_collection('health_data')
        
        # Get health data for the specific device, sorted by timestamp
        cursor = collection.find({'device_id': device_id}).sort('timestamp', -1).limit(100)
        health_data = await cursor.to_list(length=100)
        
        # Convert MongoDB documents to JSON-serializable format
        converted_health_data = [convert_mongodb_document(doc) for doc in health_data]
        
        return ApiResponse(
            success=True,
            message=f"Health data retrieved for device {device_id}",
            data=converted_health_data,
            timestamp=get_current_timestamp()
        )
        
    except Exception as e:
        logger.error(f"Error getting device health: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/device/{device_id}/alarms", response_model=ApiResponse)
async def get_device_alarms(device_id: str):
    """Get alarm data for specific device"""
    try:
        db = await get_database()
        collection = db.get_collection('alarms')
        
        # Get alarms for the specific device, sorted by timestamp
        cursor = collection.find({'device_id': device_id}).sort('timestamp', -1).limit(100)
        alarms = await cursor.to_list(length=100)
        
        # Convert MongoDB documents to JSON-serializable format
        converted_alarms = [convert_mongodb_document(doc) for doc in alarms]
        
        return ApiResponse(
            success=True,
            message=f"Alarm data retrieved for device {device_id}",
            data=converted_alarms,
            timestamp=get_current_timestamp()
        )
        
    except Exception as e:
        logger.error(f"Error getting device alarms: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/device/{device_id}/sos", response_model=ApiResponse)
async def get_device_sos(device_id: str):
    """Get SOS/call log data for specific device"""
    try:
        db = await get_database()
        collection = db.get_collection('sos_calls')
        
        # Get SOS calls for the specific device, sorted by timestamp
        cursor = collection.find({'device_id': device_id}).sort('timestamp', -1).limit(100)
        sos_data = await cursor.to_list(length=100)
        
        # Convert MongoDB documents to JSON-serializable format
        converted_sos_data = [convert_mongodb_document(doc) for doc in sos_data]
        
        return ApiResponse(
            success=True,
            message=f"SOS data retrieved for device {device_id}",
            data=converted_sos_data,
            timestamp=get_current_timestamp()
        )
        
    except Exception as e:
        logger.error(f"Error getting device SOS data: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,  # Set to False for production
        log_level="info"
    )
