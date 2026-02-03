"""Natural language parser for cattle management commands."""
import re
from datetime import date, timedelta
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class CommandType(Enum):
    ADD_CATTLE = "add_cattle"
    MOVE = "move"
    HEALTH = "health"
    SALE = "sale"
    QUERY = "query"
    STATUS = "status"
    HELP = "help"
    UNKNOWN = "unknown"


@dataclass
class ParsedCommand:
    command_type: CommandType
    params: Dict[str, Any]
    confidence: float
    raw_text: str


class CommandParser:
    """Parse natural language cattle commands."""
    
    # Cattle type synonyms
    CATTLE_TYPES = {
        "calf": ["calf", "calve", "baby", "newborn"],
        "cow": ["cow", "mama", "momma", "mother", "dam"],
        "bull": ["bull", "sire", "daddy"],
        "steer": ["steer", "steers"],
        "heifer": ["heifer", "heifers", "young cow"],
    }
    
    # Event type patterns
    EVENT_TYPES = {
        "vet": ["vet", "veterinarian", "doctor", "checkup", "check up", "check-up"],
        "treatment": ["treat", "treatment", "medicine", "medicate", "dose", "shot", "vaccine"],
        "birth": ["born", "birth", "calved", "calving", "dropped"],
        "death": ["died", "dead", "death", "passed", "lost"],
        "note": ["note", "notes", "comment", "observe", "saw"],
    }
    
    # Location keywords
    LOCATIONS = ["pasture", "field", "barn", "corral", "pen", "woods", "hayfield"]
    
    # Query keywords
    QUERY_WORDS = ["how many", "count", "total", "list", "show", "what", "where", "status"]
    
    def parse(self, text: str) -> ParsedCommand:
        """Parse a text message into a command."""
        text = text.strip()
        lower = text.lower()
        
        # Check for help
        if lower in ["help", "?", "commands", "what can you do"]:
            return ParsedCommand(CommandType.HELP, {}, 1.0, text)
        
        # Check for status/overview
        if lower in ["status", "overview", "summary", "stats"]:
            return ParsedCommand(CommandType.STATUS, {}, 1.0, text)
        
        # Check for queries first
        if any(q in lower for q in self.QUERY_WORDS):
            return self._parse_query(text, lower)
        
        # Check for sale
        if any(w in lower for w in ["sold", "sale", "sell"]):
            return self._parse_sale(text, lower)
        
        # Check for health/vet event
        if any(any(w in lower for w in words) for words in self.EVENT_TYPES.values()):
            return self._parse_event(text, lower)
        
        # Check for movement
        if any(w in lower for w in ["moved", "move", "moving", "went", "put", "in the", "to the"]):
            return self._parse_move(text, lower)
        
        # Check for adding cattle
        if any(w in lower for w in ["add", "new", "born", "bought", "got"]):
            return self._parse_add(text, lower)
        
        # Try to infer from context
        return self._infer_command(text, lower)
    
    def _parse_add(self, text: str, lower: str) -> ParsedCommand:
        """Parse add cattle command."""
        params = {
            "type": "calf",  # Default
            "breed": "Angus",
            "birth_date": None,
            "tag": None,
            "location": None,
            "notes": None,
        }
        
        # Detect cattle type
        for ctype, keywords in self.CATTLE_TYPES.items():
            if any(k in lower for k in keywords):
                params["type"] = ctype
                break
        
        # Extract tag (look for patterns like "tag 42", "#42", "red tag", etc.)
        tag_patterns = [
            r"(?:tag\s*#?\s*)(\w+)",
            r"#(\d+)",
            r"(\w+)\s+tag",
            r"(?:number|num|no\.?)\s*(\d+)",
        ]
        for pattern in tag_patterns:
            match = re.search(pattern, lower)
            if match:
                params["tag"] = match.group(1).upper()
                break
        
        # Generate tag if not found
        if not params["tag"]:
            params["tag"] = f"NEW-{date.today().strftime('%m%d')}"
        
        # Check for "today" or date
        if "today" in lower:
            params["birth_date"] = date.today()
        elif "yesterday" in lower:
            params["birth_date"] = date.today() - timedelta(days=1)
        
        # Extract color for notes
        colors = ["red", "blue", "green", "yellow", "white", "black", "orange"]
        for color in colors:
            if color in lower:
                params["notes"] = f"{color} tag" if "tag" in lower else color
                if params["tag"] == f"NEW-{date.today().strftime('%m%d')}":
                    params["tag"] = f"{color.upper()}-{date.today().strftime('%m%d')}"
                break
        
        # Extract location
        for loc in self.LOCATIONS:
            if loc in lower:
                # Get the full location phrase
                match = re.search(rf"(\w+\s+)?{loc}", lower)
                if match:
                    params["location"] = match.group(0).title()
                break
        
        return ParsedCommand(CommandType.ADD_CATTLE, params, 0.8, text)
    
    def _parse_move(self, text: str, lower: str) -> ParsedCommand:
        """Parse move command."""
        params = {"tag": None, "location": None}
        
        # Extract tag/ID
        tag_match = re.search(r"(?:cow|bull|calf|steer|heifer|#)\s*(\d+)", lower)
        if tag_match:
            params["tag"] = tag_match.group(1)
        
        # Extract location
        loc_patterns = [
            r"(?:to|in|at)\s+(?:the\s+)?(\w+\s+(?:pasture|field|pen|barn|corral))",
            r"(?:to|in|at)\s+(?:the\s+)?(\w+)",
            r"(north|south|east|west|back|front|main|new)\s+(?:pasture|field)",
        ]
        for pattern in loc_patterns:
            match = re.search(pattern, lower)
            if match:
                params["location"] = match.group(1).title()
                break
        
        confidence = 0.9 if params["tag"] and params["location"] else 0.6
        return ParsedCommand(CommandType.MOVE, params, confidence, text)
    
    def _parse_event(self, text: str, lower: str) -> ParsedCommand:
        """Parse health/event command."""
        params = {"tag": None, "event_type": "note", "details": text, "date": date.today()}
        
        # Detect event type
        for etype, keywords in self.EVENT_TYPES.items():
            if any(k in lower for k in keywords):
                params["event_type"] = etype
                break
        
        # Extract tag
        tag_match = re.search(r"(?:cow|bull|calf|steer|heifer|#)\s*(\d+)", lower)
        if tag_match:
            params["tag"] = tag_match.group(1)
        
        # Extract condition/details
        conditions = [
            "pink eye", "pinkeye", "limp", "limping", "sick", "fever",
            "bloat", "prolapse", "mastitis", "foot rot", "scours", "pneumonia"
        ]
        for condition in conditions:
            if condition in lower:
                params["details"] = condition.title()
                break
        
        return ParsedCommand(CommandType.HEALTH, params, 0.85, text)
    
    def _parse_sale(self, text: str, lower: str) -> ParsedCommand:
        """Parse sale command."""
        params = {
            "head_count": 1,
            "price_per_lb": None,
            "avg_weight": None,
            "cattle_type": "steer",
            "buyer": None,
            "date": date.today(),
        }
        
        # Extract head count
        count_match = re.search(r"(\d+)\s*(?:head|steers?|heifers?|cows?|bulls?)", lower)
        if count_match:
            params["head_count"] = int(count_match.group(1))
        else:
            count_match = re.search(r"sold\s+(\d+)", lower)
            if count_match:
                params["head_count"] = int(count_match.group(1))
        
        # Extract price per pound
        price_match = re.search(r"\$?([\d.]+)\s*(?:/|\s*per\s*)?(?:lb|pound)", lower)
        if price_match:
            params["price_per_lb"] = float(price_match.group(1))
        
        # Extract weight
        weight_match = re.search(r"(\d+)\s*(?:lb|lbs|pounds?)|avg\s+(\d+)|average\s+(\d+)", lower)
        if weight_match:
            params["avg_weight"] = float(weight_match.group(1) or weight_match.group(2) or weight_match.group(3))
        
        # Detect cattle type
        for ctype in ["steer", "heifer", "cow", "bull", "calf"]:
            if ctype in lower:
                params["cattle_type"] = ctype
                break
        
        return ParsedCommand(CommandType.SALE, params, 0.9, text)
    
    def _parse_query(self, text: str, lower: str) -> ParsedCommand:
        """Parse query command."""
        params = {"query_type": "count", "filter": {}}
        
        # Determine query type
        if "where" in lower:
            params["query_type"] = "location"
            tag_match = re.search(r"(?:cow|bull|calf|is|#)\s*(\d+)", lower)
            if tag_match:
                params["filter"]["tag"] = tag_match.group(1)
        
        elif any(w in lower for w in ["how many", "count", "total"]):
            params["query_type"] = "count"
            
            # Filter by type
            for ctype in self.CATTLE_TYPES:
                if ctype in lower:
                    params["filter"]["type"] = ctype
                    break
            
            # Time filter
            if "this month" in lower or "month" in lower:
                params["filter"]["since"] = date.today().replace(day=1)
            elif "this year" in lower or "year" in lower or "ytd" in lower:
                params["filter"]["since"] = date(date.today().year, 1, 1)
            elif "today" in lower:
                params["filter"]["since"] = date.today()
        
        elif "list" in lower or "show" in lower or "all" in lower:
            params["query_type"] = "list"
            for ctype in self.CATTLE_TYPES:
                if ctype in lower:
                    params["filter"]["type"] = ctype
                    break
        
        return ParsedCommand(CommandType.QUERY, params, 0.85, text)
    
    def _infer_command(self, text: str, lower: str) -> ParsedCommand:
        """Try to infer command from context."""
        # Check for number that might be a cattle tag
        tag_match = re.search(r"^(\d+)\s+(.+)$", text)
        if tag_match:
            tag = tag_match.group(1)
            rest = tag_match.group(2).lower()
            
            # "42 sick" -> health event
            if any(w in rest for w in ["sick", "limping", "down", "problem"]):
                return ParsedCommand(
                    CommandType.HEALTH,
                    {"tag": tag, "event_type": "note", "details": rest},
                    0.7,
                    text
                )
        
        return ParsedCommand(CommandType.UNKNOWN, {"raw": text}, 0.0, text)


# Helper to generate responses
def generate_response(command: ParsedCommand, result: Dict[str, Any]) -> str:
    """Generate a human-friendly response."""
    if command.command_type == CommandType.HELP:
        return """FarmOps Commands:
• Add calf born today red tag
• Cow 42 moved to north pasture  
• How many calves this month
• Vet visit cow 15 pink eye
• Sold 5 steers $1.85/lb avg 1100
• Status (for overview)
• Help (this message)"""
    
    if command.command_type == CommandType.STATUS:
        stats = result
        return f"""🐄 Farm Status:
Total: {stats.get('total_head', 0)} head
Calves YTD: {stats.get('calves_ytd', 0)}
Sales YTD: {stats.get('sales_ytd_head', 0)} head (${stats.get('sales_ytd_amount', 0):,.0f})"""
    
    if command.command_type == CommandType.ADD_CATTLE:
        return f"✓ Added {command.params.get('type', 'cattle')} - tag {result.get('tag', 'N/A')}"
    
    if command.command_type == CommandType.MOVE:
        return f"✓ Moved #{command.params.get('tag')} to {command.params.get('location')}"
    
    if command.command_type == CommandType.HEALTH:
        return f"✓ Logged {command.params.get('event_type')} for #{command.params.get('tag')}: {command.params.get('details')}"
    
    if command.command_type == CommandType.SALE:
        p = command.params
        amt = (p.get('price_per_lb', 0) or 0) * (p.get('avg_weight', 0) or 0) * p.get('head_count', 1)
        return f"✓ Recorded sale: {p.get('head_count')} {p.get('cattle_type')}(s) - ${amt:,.0f}"
    
    if command.command_type == CommandType.QUERY:
        if command.params.get("query_type") == "count":
            filter_desc = command.params.get("filter", {}).get("type", "cattle")
            return f"Count: {result.get('count', 0)} {filter_desc}"
        elif command.params.get("query_type") == "location":
            return f"#{command.params['filter'].get('tag')} is at {result.get('location', 'unknown')}"
        elif command.params.get("query_type") == "list":
            count = len(result.get("cattle", []))
            return f"Found {count} cattle. Check dashboard for full list."
    
    return "Command received. Check dashboard for details."
