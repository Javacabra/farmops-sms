"""FarmOps SMS - Main FastAPI Application."""
import os
import io
import httpx
from datetime import date
from typing import Optional

from fastapi import FastAPI, Request, Form, HTTPException, Response
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.request_validator import RequestValidator
from dotenv import load_dotenv

from .database import CattleDB, init_db_sync, get_db
from .parser import CommandParser, CommandType, generate_response

load_dotenv()

# Initialize
app = FastAPI(title="FarmOps SMS", description="Cattle management via SMS/Voice")
parser = CommandParser()

# Templates and static
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Config
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
AUTHORIZED_NUMBERS = [n.strip() for n in os.getenv("AUTHORIZED_NUMBERS", "").split(",") if n.strip()]
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


@app.on_event("startup")
async def startup():
    """Initialize database on startup."""
    init_db_sync()


def validate_twilio_request(request: Request, params: dict) -> bool:
    """Validate request is from Twilio."""
    if not TWILIO_AUTH_TOKEN:
        return True  # Skip validation in dev
    
    validator = RequestValidator(TWILIO_AUTH_TOKEN)
    signature = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)
    return validator.validate(url, params, signature)


def check_authorized(phone: str) -> bool:
    """Check if phone number is authorized."""
    if not AUTHORIZED_NUMBERS:
        return True  # No restrictions in dev
    return phone in AUTHORIZED_NUMBERS


# =============================================================================
# SMS Webhooks
# =============================================================================

@app.post("/sms/incoming")
async def sms_incoming(
    request: Request,
    Body: str = Form(...),
    From: str = Form(...),
    To: str = Form(None),
):
    """Handle incoming SMS messages."""
    # Validate request
    params = {"Body": Body, "From": From}
    if To:
        params["To"] = To
    
    # Log incoming message
    await CattleDB.log_message(From, "inbound", Body)
    
    # Check authorization
    if not check_authorized(From):
        response = MessagingResponse()
        response.message("Unauthorized. Contact admin to add your number.")
        return Response(content=str(response), media_type="application/xml")
    
    # Parse command
    command = parser.parse(Body)
    result = {}
    
    try:
        # Execute command
        if command.command_type == CommandType.ADD_CATTLE:
            result = await CattleDB.add_cattle(
                tag=command.params.get("tag"),
                cattle_type=command.params.get("type", "calf"),
                breed=command.params.get("breed", "Angus"),
                birth_date=command.params.get("birth_date"),
                location=command.params.get("location"),
                notes=command.params.get("notes"),
            )
        
        elif command.command_type == CommandType.MOVE:
            success = await CattleDB.update_location(
                tag=command.params.get("tag"),
                location=command.params.get("location"),
            )
            result = {"success": success}
        
        elif command.command_type == CommandType.HEALTH:
            result = await CattleDB.add_event(
                cattle_tag=command.params.get("tag"),
                event_type=command.params.get("event_type"),
                details=command.params.get("details"),
                event_date=command.params.get("date"),
            )
        
        elif command.command_type == CommandType.SALE:
            result = await CattleDB.add_sale(
                head_count=command.params.get("head_count", 1),
                price_per_lb=command.params.get("price_per_lb"),
                avg_weight=command.params.get("avg_weight"),
                cattle_type=command.params.get("cattle_type", "steer"),
                buyer=command.params.get("buyer"),
                sale_date=command.params.get("date"),
            )
        
        elif command.command_type == CommandType.QUERY:
            query_type = command.params.get("query_type")
            filters = command.params.get("filter", {})
            
            if query_type == "count":
                count = await CattleDB.count_cattle(
                    cattle_type=filters.get("type"),
                    since_date=filters.get("since"),
                )
                result = {"count": count}
            elif query_type == "location":
                cattle = await CattleDB.get_cattle(tag=filters.get("tag"))
                result = {"location": cattle.get("location_name") if cattle else "not found"}
            elif query_type == "list":
                cattle = await CattleDB.get_all_cattle()
                result = {"cattle": cattle}
        
        elif command.command_type == CommandType.STATUS:
            result = await CattleDB.get_stats()
        
        elif command.command_type == CommandType.HELP:
            result = {}
        
        else:
            result = {"error": "unknown command"}
    
    except Exception as e:
        result = {"error": str(e)}
    
    # Generate response
    reply = generate_response(command, result)
    
    # Log outgoing
    await CattleDB.log_message(From, "outbound", reply, str(command.command_type.value))
    
    # Send TwiML response
    response = MessagingResponse()
    response.message(reply)
    return Response(content=str(response), media_type="application/xml")


# =============================================================================
# Voice Webhooks
# =============================================================================

@app.post("/voice/incoming")
async def voice_incoming(
    request: Request,
    From: str = Form(None),
):
    """Handle incoming voice call - gather speech input."""
    response = VoiceResponse()
    
    if not check_authorized(From or ""):
        response.say("Sorry, this number is not authorized.", voice="alice")
        response.hangup()
        return Response(content=str(response), media_type="application/xml")
    
    gather = Gather(
        input="speech",
        action="/voice/process",
        method="POST",
        speech_timeout="auto",
        language="en-US",
    )
    gather.say(
        "Welcome to FarmOps. Please tell me what you'd like to record. "
        "For example, say 'add calf born today' or 'cow 42 moved to north pasture'.",
        voice="alice"
    )
    response.append(gather)
    
    # If no input, prompt again
    response.say("I didn't catch that. Please call back and try again.", voice="alice")
    
    return Response(content=str(response), media_type="application/xml")


@app.post("/voice/process")
async def voice_process(
    request: Request,
    SpeechResult: str = Form(None),
    From: str = Form(None),
):
    """Process voice input - transcription from Twilio."""
    response = VoiceResponse()
    
    if not SpeechResult:
        response.say("I didn't catch that. Please try again.", voice="alice")
        response.redirect("/voice/incoming")
        return Response(content=str(response), media_type="application/xml")
    
    # Log the transcription
    await CattleDB.log_message(From or "voice", "inbound", f"[VOICE] {SpeechResult}")
    
    # Parse and execute command (same as SMS)
    command = parser.parse(SpeechResult)
    result = {}
    
    try:
        if command.command_type == CommandType.ADD_CATTLE:
            result = await CattleDB.add_cattle(
                tag=command.params.get("tag"),
                cattle_type=command.params.get("type", "calf"),
                birth_date=command.params.get("birth_date"),
                location=command.params.get("location"),
                notes=command.params.get("notes"),
            )
        elif command.command_type == CommandType.MOVE:
            await CattleDB.update_location(
                tag=command.params.get("tag"),
                location=command.params.get("location"),
            )
            result = {"success": True}
        elif command.command_type == CommandType.HEALTH:
            result = await CattleDB.add_event(
                cattle_tag=command.params.get("tag"),
                event_type=command.params.get("event_type"),
                details=command.params.get("details"),
            )
        elif command.command_type == CommandType.SALE:
            result = await CattleDB.add_sale(
                head_count=command.params.get("head_count", 1),
                price_per_lb=command.params.get("price_per_lb"),
                avg_weight=command.params.get("avg_weight"),
                cattle_type=command.params.get("cattle_type", "steer"),
            )
        elif command.command_type == CommandType.STATUS:
            result = await CattleDB.get_stats()
        elif command.command_type == CommandType.QUERY:
            if command.params.get("query_type") == "count":
                count = await CattleDB.count_cattle(
                    cattle_type=command.params.get("filter", {}).get("type"),
                    since_date=command.params.get("filter", {}).get("since"),
                )
                result = {"count": count}
    except Exception as e:
        result = {"error": str(e)}
    
    # Generate and speak response
    reply = generate_response(command, result)
    await CattleDB.log_message(From or "voice", "outbound", f"[VOICE] {reply}")
    
    response.say(reply, voice="alice")
    
    # Ask if they want to do more
    gather = Gather(
        input="speech",
        action="/voice/process",
        method="POST",
        speech_timeout="auto",
    )
    gather.say("Is there anything else?", voice="alice")
    response.append(gather)
    
    response.say("Goodbye!", voice="alice")
    response.hangup()
    
    return Response(content=str(response), media_type="application/xml")


# =============================================================================
# Web Dashboard
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard."""
    stats = await CattleDB.get_stats()
    cattle = await CattleDB.get_all_cattle()
    locations = await CattleDB.get_locations()
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stats": stats,
        "cattle": cattle,
        "locations": locations,
        "today": date.today(),
    })


@app.get("/api/stats")
async def api_stats():
    """Get stats as JSON."""
    return await CattleDB.get_stats()


@app.get("/api/cattle")
async def api_cattle(status: str = "active"):
    """Get all cattle as JSON."""
    return await CattleDB.get_all_cattle(status)


@app.get("/api/cattle/{tag}")
async def api_cattle_detail(tag: str):
    """Get single cattle record."""
    cattle = await CattleDB.get_cattle(tag=tag)
    if not cattle:
        raise HTTPException(status_code=404, detail="Cattle not found")
    return cattle


# =============================================================================
# Health Check
# =============================================================================

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "farmops-sms"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
