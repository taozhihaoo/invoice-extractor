"""Strict JSON schemas for OpenAI structured outputs and the system prompts.

The schemas use OpenAI strict mode: every field is required, nullable fields
are typed ``["...", "null"]`` and ``additionalProperties`` is false, so the
model cannot invent extra keys.
"""

INVOICE_JSON_SCHEMA = {
    "name": "invoice_data",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "supplier": {
                "type": ["string", "null"],
                "description": "Supplier / company name exactly as printed on the document.",
            },
            "invoice_number": {
                "type": ["string", "null"],
                "description": "Invoice identifier exactly as printed on the document.",
            },
            "invoice_date": {
                "type": ["string", "null"],
                "description": "Invoice issue date as ISO 8601 (YYYY-MM-DD).",
            },
            "due_date": {
                "type": ["string", "null"],
                "description": "Payment due date as ISO 8601 (YYYY-MM-DD).",
            },
            "subtotal": {
                "type": ["number", "null"],
                "description": "Net amount before tax, as a plain number.",
            },
            "tax": {
                "type": ["number", "null"],
                "description": "Tax / VAT amount, as a plain number.",
            },
            "total": {
                "type": ["number", "null"],
                "description": "Gross amount due, as a plain number.",
            },
            "currency": {
                "type": ["string", "null"],
                "description": "ISO 4217 currency code, uppercase (e.g. USD, EUR).",
            },
        },
        "required": [
            "supplier",
            "invoice_number",
            "invoice_date",
            "due_date",
            "subtotal",
            "tax",
            "total",
            "currency",
        ],
        "additionalProperties": False,
    },
}

CLASSIFICATION_JSON_SCHEMA = {
    "name": "document_classification",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "document_type": {
                "type": "string",
                "enum": ["invoice", "receipt", "unknown"],
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["document_type", "confidence"],
        "additionalProperties": False,
    },
}

SYSTEM_EXTRACT_PROMPT = """You are an invoice data extraction engine.
Extract only information that is explicitly printed in the document.
Never guess and never infer missing values: if a field is not present, return null.
Rules:
- Dates must be ISO 8601 (YYYY-MM-DD).
- Amounts must be plain numbers without currency symbols or thousands separators.
- Currency must be an uppercase ISO 4217 code.
- Ignore line items; return only the document-level fields requested."""

SYSTEM_CLASSIFY_PROMPT = """You classify document text into exactly one type:
"invoice", "receipt" or "unknown".
Return a confidence between 0 and 1 that reflects how certain you are.
Use "unknown" when the text does not clearly match either type; be conservative."""
