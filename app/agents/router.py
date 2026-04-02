"""Intent router - classifies user messages and determines the funnel stage."""

import re
from datetime import datetime, timedelta


# Horário comercial
BUSINESS_HOUR_START = 8   # 08:00
BUSINESS_HOUR_END = 18    # 18:00
BUSINESS_DAYS = {0, 1, 2, 3, 4}  # seg-sex (monday=0)

WEEKDAY_MAP = {
    "segunda": 0, "segunda-feira": 0, "seg": 0,
    "terça": 1, "terca": 1, "terça-feira": 1, "terca-feira": 1, "ter": 1,
    "quarta": 2, "quarta-feira": 2, "qua": 2,
    "quinta": 3, "quinta-feira": 3, "qui": 3,
    "sexta": 4, "sexta-feira": 4, "sex": 4,
    "sábado": 5, "sabado": 5, "sab": 5,
    "domingo": 6, "dom": 6,
}

MONTH_MAP = {
    "janeiro": 1, "jan": 1, "fevereiro": 2, "fev": 2,
    "março": 3, "marco": 3, "mar": 3, "abril": 4, "abr": 4,
    "maio": 5, "mai": 5, "junho": 6, "jun": 6,
    "julho": 7, "jul": 7, "agosto": 8, "ago": 8,
    "setembro": 9, "set": 9, "outubro": 10, "out": 10,
    "novembro": 11, "nov": 11, "dezembro": 12, "dez": 12,
}

RELATIVE_DAY_MAP = {
    "hoje": 0, "amanhã": 1, "amanha": 1,
    "depois de amanhã": 2, "depois de amanha": 2,
}


class DateTimeInfo:
    """Parsed date/time from user message."""

    def __init__(self):
        self.day: int | None = None
        self.month: int | None = None
        self.year: int = datetime.now().year
        self.hour: int | None = None
        self.minute: int = 0
        self.weekday_name: str = ""
        self.raw_text: str = ""
        self.is_valid: bool = False
        self.is_business_hours: bool = False
        self.resolved_date: datetime | None = None

    def resolve(self) -> None:
        """Resolve partial date info into a full datetime."""
        now = datetime.now()

        if self.day and self.month:
            try:
                self.resolved_date = datetime(
                    self.year, self.month, self.day,
                    self.hour or 9, self.minute
                )
                # Se a data já passou neste ano, assume próximo ano
                if self.resolved_date < now:
                    self.resolved_date = self.resolved_date.replace(year=self.year + 1)
            except ValueError:
                self.resolved_date = None
        elif self.day and not self.month:
            # "dia 15" → assume mês atual ou próximo
            try:
                self.resolved_date = datetime(
                    now.year, now.month, self.day,
                    self.hour or 9, self.minute
                )
                if self.resolved_date < now:
                    # Próximo mês
                    if now.month == 12:
                        self.resolved_date = datetime(now.year + 1, 1, self.day, self.hour or 9, self.minute)
                    else:
                        self.resolved_date = datetime(now.year, now.month + 1, self.day, self.hour or 9, self.minute)
            except ValueError:
                self.resolved_date = None

        if self.resolved_date:
            self.is_valid = True
            self._check_business_hours()

    def _check_business_hours(self) -> None:
        """Check if the resolved datetime falls within business hours."""
        if not self.resolved_date:
            self.is_business_hours = False
            return
        h = self.hour if self.hour is not None else 9
        wd = self.resolved_date.weekday()
        self.is_business_hours = (
            wd in BUSINESS_DAYS and BUSINESS_HOUR_START <= h < BUSINESS_HOUR_END
        )

    def format_display(self) -> str:
        """Format for display in WhatsApp message."""
        if not self.resolved_date:
            return ""
        dias = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
        wd = dias[self.resolved_date.weekday()]
        date_str = self.resolved_date.strftime("%d/%m")
        if self.hour is not None:
            return f"{wd}, {date_str} às {self.hour:02d}:{self.minute:02d}"
        return f"{wd}, {date_str}"

    def suggest_alternative(self) -> str:
        """Suggest a valid business hour alternative."""
        if not self.resolved_date:
            return ""
        dt = self.resolved_date
        # Se fim de semana, mover para segunda
        while dt.weekday() not in BUSINESS_DAYS:
            dt += timedelta(days=1)
        # Se fora do horário, ajustar
        h = self.hour if self.hour is not None else 9
        if h < BUSINESS_HOUR_START:
            h = BUSINESS_HOUR_START
        elif h >= BUSINESS_HOUR_END:
            h = BUSINESS_HOUR_START
            dt += timedelta(days=1)
            while dt.weekday() not in BUSINESS_DAYS:
                dt += timedelta(days=1)
        alt = dt.replace(hour=h, minute=0)
        dias = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
        wd = dias[alt.weekday()]
        return f"{wd}, {alt.strftime('%d/%m')} às {h:02d}:00"


def extract_datetime(text: str) -> DateTimeInfo | None:
    """Extract date and time information from a user message."""
    text_lower = text.lower().strip()
    info = DateTimeInfo()
    info.raw_text = text
    found_something = False
    now = datetime.now()

    # 1. Relative days: "hoje", "amanhã", "depois de amanhã"
    for term, delta in sorted(RELATIVE_DAY_MAP.items(), key=lambda x: -len(x[0])):
        if term in text_lower:
            target = now + timedelta(days=delta)
            info.day = target.day
            info.month = target.month
            info.year = target.year
            found_something = True
            break

    # 2. Weekday: "terça", "quinta-feira", etc.
    if not found_something:
        for term, wd in sorted(WEEKDAY_MAP.items(), key=lambda x: -len(x[0])):
            if re.search(r"\b" + re.escape(term) + r"\b", text_lower):
                info.weekday_name = term
                # Calculate next occurrence
                today_wd = now.weekday()
                days_ahead = (wd - today_wd) % 7
                if days_ahead == 0:
                    days_ahead = 7  # Próxima semana se for hoje
                target = now + timedelta(days=days_ahead)
                info.day = target.day
                info.month = target.month
                info.year = target.year
                found_something = True
                break

    # 3. Explicit date: "dia 15", "15/04", "15 de abril"
    # "dia X"
    m = re.search(r"\bdia\s+(\d{1,2})\b", text_lower)
    if m:
        info.day = int(m.group(1))
        found_something = True

    # "DD/MM" or "DD/MM/YYYY"
    m = re.search(r"\b(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?\b", text_lower)
    if m:
        info.day = int(m.group(1))
        info.month = int(m.group(2))
        if m.group(3):
            y = int(m.group(3))
            info.year = y if y > 100 else 2000 + y
        found_something = True

    # "15 de abril", "5 de março"
    for month_name, month_num in MONTH_MAP.items():
        pattern = rf"\b(\d{{1,2}})\s+de\s+{re.escape(month_name)}\b"
        m = re.search(pattern, text_lower)
        if m:
            info.day = int(m.group(1))
            info.month = month_num
            found_something = True
            break

    # 4. Time extraction: "14h", "14:30", "às 10", "10 horas", "14h30"
    time_patterns = [
        (r"\b(\d{1,2})\s*[h:]\s*(\d{2})\b", True),       # 14h30, 14:30
        (r"\b(\d{1,2})\s*h\b", False),                      # 14h
        (r"\bàs\s+(\d{1,2})\b", False),                     # às 14
        (r"\b(\d{1,2})\s*horas?\b", False),                  # 10 horas
        (r"\bàs\s+(\d{1,2})\s*[h:]\s*(\d{2})\b", True),    # às 14h30
    ]
    for pattern, has_minutes in time_patterns:
        m = re.search(pattern, text_lower)
        if m:
            info.hour = int(m.group(1))
            if has_minutes and m.lastindex >= 2:
                info.minute = int(m.group(2))
            found_something = True
            break

    if not found_something:
        return None

    # Fill defaults
    if not info.month and info.day:
        info.month = now.month
    if info.month and not info.day:
        info.day = now.day

    info.resolve()
    return info


class IntentRouter:
    """Classifies user intent and manages funnel stage transitions."""

    GREETING_PATTERNS = [
        r"\b(oi|olá|ola|bom dia|boa tarde|boa noite|hey|hello|eai|e ai)\b",
    ]
    SCHEDULING_PATTERNS = [
        r"\b(agendar|marcar|horário|horario|consulta|reunião|reuniao|disponibilidade|agenda)\b",
    ]
    DATETIME_PATTERNS = [
        r"\b(hoje|amanhã|amanha|depois de amanhã|segunda|terça|terca|quarta|quinta|sexta)\b",
        r"\b\d{1,2}\s*[h:]\s*\d{0,2}\b",
        r"\b\d{1,2}\s*/\s*\d{1,2}\b",
        r"\bdia\s+\d{1,2}\b",
        r"\bàs\s+\d{1,2}\b",
        r"\b\d{1,2}\s*horas?\b",
    ]
    OBJECTION_PATTERNS = [
        r"\b(pensar|depois|agora não|agora nao|mais tarde|sem tempo|ocupado|caro|medo|cancelar)\b",
        r"\b(falar|ver|conversar|alinhar|combinar)\b.{0,20}\b(esposo|esposa|marido|mulher)\b",
    ]
    QUALIFICATION_PATTERNS = [
        r"\b(reajuste|aumento|plano|saúde|saude|operadora|unimed|amil|bradesco|sulamerica|sul ?américa|hapvida|notredame)\b",
        r"\b(individual|familiar|coletivo|empresarial|adesão|adesao)\b",
        r"R?\$\s*[\d.,]+",
        r"\b(pagava|pago|paguei|ficou|foi para|subiu para|mensalidade)\b",
    ]
    CONFIRMATION_PATTERNS = [
        r"\b(sim|pode ser|ok|beleza|bora|vamos|quero|aceito|fechado|combinado|perfeito|confirmo)\b",
    ]
    REFERRAL_PATTERNS = [
        r"\b(indicação|indicacao|indicar|amigo|conhece alguém|conhece alguem|parente)\b",
    ]
    EMOTIONAL_SIGNAL_PATTERNS = {
        "anxiety": [
            r"\b(medo|receio|preocupad|insegur|aflito|nervos)\b",
        ],
        "frustration": [
            r"\b(absurdo|caro|pesado|injusto|indignad|abusiv[oa]|surreal)\b",
        ],
        "urgency": [
            r"\b(urgente|hoje|agora|o quanto antes|mais rapido|mais rápido|imediato)\b",
        ],
        "hesitation": [
            r"\b(não sei|nao sei|vou pensar|depois vejo|talvez|deixa eu ver)\b",
        ],
    }
    OBJECTION_TYPE_PATTERNS = {
        "cancellation_fear": [
            r"\b(medo.*cancel|cancelar|cancelamento|cancelado)\b",
        ],
        "spouse_alignment": [
            r"\b(falar|ver|conversar|alinhar|combinar)\b.{0,20}\b(espos[oa]|marido|mulher)\b",
        ],
        "price_pressure": [
            r"\b(caro|sem dinheiro|apertado|pesado|não consigo pagar|nao consigo pagar)\b",
        ],
        "timing": [
            r"\b(sem tempo|ocupado|depois|mais tarde|corrido)\b",
        ],
        "thinking": [
            r"\b(vou pensar|pensar|deixa eu pensar|deixa eu ver|avaliar)\b",
        ],
    }

    @staticmethod
    def classify_intent(text: str) -> str:
        """Classify the primary intent of the user message."""
        text_lower = text.lower().strip()

        # Scheduling explicit
        if any(re.search(p, text_lower) for p in IntentRouter.SCHEDULING_PATTERNS):
            return "scheduling"
        # Date/time mentioned → also scheduling intent
        if any(re.search(p, text_lower) for p in IntentRouter.DATETIME_PATTERNS):
            return "scheduling"
        if any(re.search(p, text_lower) for p in IntentRouter.OBJECTION_PATTERNS):
            return "objection"
        if any(re.search(p, text_lower) for p in IntentRouter.CONFIRMATION_PATTERNS):
            return "confirmation"
        if any(re.search(p, text_lower) for p in IntentRouter.REFERRAL_PATTERNS):
            return "referral"
        if any(re.search(p, text_lower) for p in IntentRouter.QUALIFICATION_PATTERNS):
            return "qualification"
        if any(re.search(p, text_lower) for p in IntentRouter.GREETING_PATTERNS):
            return "greeting"
        return "general"

    @staticmethod
    def determine_stage_transition(current_stage: str, intent: str) -> str:
        """Determine if the funnel stage should advance."""
        transitions = {
            "abordagem_inicial": {
                "greeting": "abordagem_inicial",
                "qualification": "qualificacao",
                "confirmation": "qualificacao",
                "scheduling": "agendamento",
                "general": "abordagem_inicial",
            },
            "qualificacao": {
                "qualification": "qualificacao",
                "confirmation": "oferta_consulta",
                "scheduling": "agendamento",
                "general": "qualificacao",
            },
            "oferta_consulta": {
                "confirmation": "agendamento",
                "scheduling": "agendamento",
                "objection": "tratamento_objecao",
                "general": "oferta_consulta",
            },
            "tratamento_objecao": {
                "confirmation": "agendamento",
                "scheduling": "agendamento",
                "general": "tratamento_objecao",
            },
            "agendamento": {
                "confirmation": "confirmacao_consulta",
                "scheduling": "agendamento",
                "general": "agendamento",
            },
            "confirmacao_consulta": {
                "general": "confirmacao_consulta",
            },
            "pos_reuniao": {
                "confirmation": "fechamento",
                "objection": "followup_pos_reuniao",
                "general": "pos_reuniao",
            },
            "followup_pos_reuniao": {
                "confirmation": "fechamento",
                "general": "followup_pos_reuniao",
            },
            "fechamento": {
                "referral": "indicacao_ativa",
                "general": "fechamento",
            },
            "indicacao_ativa": {
                "general": "indicacao_ativa",
            },
        }

        stage_map = transitions.get(current_stage, {})
        return stage_map.get(intent, current_stage)

    @staticmethod
    def extract_qualification_data(text: str) -> dict:
        """Extract qualification data from user message."""
        data = {}
        text_lower = text.lower()

        # Extract monetary values
        money = []
        money.extend(re.findall(r"R\$\s*([\d\.,]+)", text))
        paired_values = re.findall(
            r"\b(?:era|era de|foi de|subiu de|passou de|saiu de)\s*"
            r"(?:r\$\s*)?([\d\.,]+)\s*(?:para|pra)\s*(?:r\$\s*)?([\d\.,]+)\b",
            text_lower,
        )
        for before, after in paired_values:
            money.extend((before, after))
        payment_context_terms = ["pagava", "pago", "paguei", "ficou", "foi para", "subiu para", "aumento", "reajuste", "mensalidade", "valor"]
        money.extend(
            re.findall(
                r"(?:pagava|pago|paguei|ficou|foi para|subiu para|aumento|reajuste|mensalidade|valor(?:\s+do\s+plano)?)"
                r"[^\d]{0,15}(\d{2,5}(?:[.,]\d{2})?)",
                text_lower,
            )
        )
        if any(term in text_lower for term in payment_context_terms):
            money.extend(re.findall(r"\b\d{2,5}(?:[.,]\d{2})?\b", text_lower))
        normalized_values = []
        for raw_value in money:
            cleaned = raw_value.replace(".", "").replace(",", ".")
            try:
                amount = float(cleaned)
            except ValueError:
                continue
            if not 50 <= amount <= 100000:
                continue
            formatted = f"{amount:.2f}"
            if formatted not in normalized_values:
                normalized_values.append(formatted)
        if normalized_values:
            data["valores_mencionados"] = normalized_values[:2]

        # Detect operator
        operators = {
            "unimed": "Unimed",
            "amil": "Amil",
            "bradesco": "Bradesco Saúde",
            "sulamerica": "SulAmérica",
            "sul américa": "SulAmérica",
            "hapvida": "Hapvida",
            "notredame": "NotreDame",
            "notre dame": "NotreDame",
            "prevent": "Prevent Senior",
            "porto seguro": "Porto Seguro",
        }
        for key, name in operators.items():
            if re.search(r"\b" + re.escape(key) + r"\b", text_lower):
                data["operadora"] = name
                break

        # Detect plan type
        plan_types = {
            "individual": "individual",
            "familiar": "familiar",
            "coletivo": "coletivo por adesão",
            "adesão": "coletivo por adesão",
            "adesao": "coletivo por adesão",
            "empresarial": "empresarial",
        }
        for key, ptype in plan_types.items():
            if key in text_lower:
                data["tipo_plano"] = ptype
                break

        # Detect if beneficiaries are family members
        if any(term in text_lower for term in ["família", "familia", "esposa", "esposo", "marido", "filho", "filha", "dependente"]):
            data["beneficiarios_familia"] = "sim"
        elif any(term in text_lower for term in ["só eu", "so eu", "sozinho", "apenas eu"]):
            data["beneficiarios_familia"] = "não"

        # Detect year
        years = re.findall(r"\b(19\d{2}|20[0-2]\d)\b", text)
        if years:
            data["ano_contratacao"] = years[0]

        return data

    @staticmethod
    def detect_objection_type(text: str) -> str:
        text_lower = text.lower().strip()
        for objection_type, patterns in IntentRouter.OBJECTION_TYPE_PATTERNS.items():
            if any(re.search(pattern, text_lower) for pattern in patterns):
                return objection_type
        return "none"

    @staticmethod
    def detect_emotional_signal(text: str) -> str:
        text_lower = text.lower().strip()
        for signal, patterns in IntentRouter.EMOTIONAL_SIGNAL_PATTERNS.items():
            if any(re.search(pattern, text_lower) for pattern in patterns):
                return signal
        return "neutral"
