"""Main attendant agent - orchestrates the full conversation flow."""

import re
from datetime import datetime, timedelta

from app.agents.router import (
    BUSINESS_DAYS,
    BUSINESS_HOUR_END,
    BUSINESS_HOUR_START,
    DateTimeInfo,
    IntentRouter,
    extract_datetime,
)
from app.memory.user_memory import (
    get_user_profile,
    save_user_profile,
    get_chat_history,
    add_to_history,
    get_stage,
    set_stage,
)
from app.rag.chain import generate_response
from app.scheduling.oncehub import get_scheduling_message

WEEKDAYS_PT = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
QUALIFICATION_FIELD_LABELS = {
    "valores do plano antes e depois do reajuste": ("valor_antes", "valor_depois"),
    "operadora": ("operadora",),
    "tipo do plano": ("tipo_plano",),
    "ano de contratação": ("ano_contratacao",),
    "beneficiários são da família": ("beneficiarios_familia",),
}
MINIMUM_QUALIFICATION_KEYS = (
    "operadora",
    "tipo_plano",
    "valor_antes",
    "valor_depois",
    "ano_contratacao",
)
META_RESPONSE_PATTERNS = (
    r"^\s*\(.*(?:usei|técnica|tecnica|gatilho|cta|call[- ]to[- ]action|mensagem curta|"
    r"foco na solução|foco na solucao|linguagem simples|alternativas controladas|"
    r"confirmação de viabilidade|confirmacao de viabilidade).*\)\s*$",
    r"^\s*usei\s+.*$",
    r"^\s*observações?\s+estratégicas?:?\s*$",
)
SOFTENING_REPLACEMENTS = (
    (r"\bclaramente abusiv[oa]\b", "com sinais de possível abuso"),
    (r"\bhá indícios fortes de abusividade\b", "há sinais que merecem análise cuidadosa"),
    (r"\bhá fortes indícios de abusividade\b", "há sinais que merecem análise cuidadosa"),
    (r"\bhá indícios fortes\b", "há indícios relevantes"),
    (
        r"\ba ação serve justamente para proteger seu contrato e evitar qualquer risco de cancelamento\b",
        "a análise busca avaliar medidas para preservar seu contrato e reduzir riscos durante a discussão",
    ),
    (
        r"\ba ação jurídica serve justamente para proteger seu contrato\b",
        "a análise jurídica busca avaliar medidas para preservar seu contrato",
    ),
    (
        r"\ba ação judicial justamente busca proteger seu contrato\b",
        "a análise jurídica busca avaliar medidas para preservar seu contrato",
    ),
    (
        r"\ba ação serve justamente para proteger seu contrato\b",
        "a análise busca avaliar medidas para preservar seu contrato",
    ),
    (
        r"\ba maioria das decisões judiciais até proíbe a operadora de cancelar o plano durante o processo\b",
        "em muitos casos, existem medidas que ajudam a reduzir esse risco enquanto a situação é analisada",
    ),
    (
        r"\bsem colocar o contrato em risco\b",
        "buscando reduzir riscos ao contrato",
    ),
    (
        r"\bprotegem seu contrato e reduzem riscos\b",
        "podem ajudar a preservar seu contrato e reduzir riscos",
    ),
    (r"\bcom certeza podemos ajudar a reverter\b", "podemos analisar com cuidado"),
    (r"\bcom certeza podemos ajudar\b", "podemos avaliar o cenário com cuidado"),
    (r"\bcom certeza\b", "ao que tudo indica"),
    (r"\bprecisamos marcar uma consulta rápida\b", "o próximo passo pode ser uma consulta rápida"),
    (r"\bna minha experiência, planos desse período têm boas chances de revisão\b", "em muitos casos, planos desse período merecem uma análise cuidadosa"),
    (r"\btem boas chances de revisão\b", "merece uma análise cuidadosa"),
    (r"\bcomo podemos buscar uma redução desse valor\b", "quais caminhos podem ser analisados no seu caso"),
    (r"\bverificar se esse reajuste foi abusivo\b", "verificar se esse reajuste pode ser questionado"),
    (r"\btem grande potencial de redução\b", "merece uma análise cuidadosa"),
    (r"\btem ótimas chances de reverter esse valor\b", "tem bons elementos para análise"),
    (r"\btem ótimas chances\b", "tem bons indícios"),
    (r"\bpodemos ajudar a reverter isso\b", "podemos analisar esse cenário"),
    (r"\bmelhor estratégia para reverter esse aumento\b", "melhor forma de analisar esse aumento"),
    (r"\bmelhor estratégia para questionar esse aumento\b", "melhor forma de analisar esse aumento"),
    (r"\bmelhor estratégia\b", "melhor caminho"),
    (r"\bavaliar as melhores estratégias para\b", "avaliar com calma caminhos possíveis, como"),
    (r"\breduzir o valor do plano\b", "ver se o reajuste pode ser revisto"),
    (r"\bpreservar sua cobertura\b", "entender os cuidados com a cobertura"),
    (r"\bmantenham a cobertura ativa\b", "ajudem a preservar a cobertura"),
    (r"\bevitem qualquer risco de cancelamento\b", "reduzam riscos durante a discussão"),
    (r"\bgarantam seus direitos\b", "busquem resguardar seus direitos"),
    (r"\bgarantir que tudo seja feito dentro da legalidade\b", "conduzir tudo com segurança jurídica"),
    (
        r"\bcomo proteger seu plano enquanto busca a revisão desse aumento\b",
        "os cuidados com o contrato enquanto esse aumento é analisado",
    ),
    (
        r"\bsem prejudicar a continuidade do plano\b",
        "considerando os cuidados com a continuidade do plano",
    ),
    (
        r"\bquer que eu reserve um horário\b",
        "Quer que eu te envie um horário disponível",
    ),
    (
        r"\bexatamente como isso funciona na prática\b",
        "com calma como isso pode funcionar no seu caso",
    ),
    (
        r"\bposso reservar um horário para você hoje mesmo\b",
        "posso te enviar um horário disponível hoje mesmo",
    ),
    (
        r"\bsem prejudicar seu plano\b",
        "com os cuidados adequados para o seu plano",
    ),
    (
        r"\bnormalmente, quando entramos com o pedido, solicitamos também medidas preventivas para evitar qualquer risco de cancelamento enquanto o caso é analisado\b",
        "quando necessário, a equipe avalia medidas para reduzir riscos enquanto o caso é analisado",
    ),
    (
        r"\bcomo podemos agir com segurança\b",
        "quais caminhos podem fazer sentido no seu caso",
    ),
    (r"\bvalor acima do justo\b", "valor que pode merecer revisão"),
    (r"\breverter esse valor\b", "questionar esse reajuste"),
    (r"\breduzir significativamente os valores\b", "buscar uma redução dos valores"),
    (r"\bquanto você pode economizar\b", "qual pode ser o melhor caminho para o seu caso"),
    (r"\bvalor justo\b", "valor mais adequado"),
)


class AttendantAgent:
    """Orchestrates the WhatsApp conversation flow for Andrade & Lemos."""

    def __init__(self):
        self.router = IntentRouter()

    async def process_message(
        self, phone: str, name: str, text: str
    ) -> str:
        """Process an incoming message and return the response."""
        # 1. Load user state
        profile = await get_user_profile(phone)
        if name and not profile.get("name"):
            profile["name"] = name
        current_stage = await get_stage(phone)
        history = await get_chat_history(phone)

        # 2. Classify intent and extract data
        intent = self.router.classify_intent(text)
        qual_data = self.router.extract_qualification_data(text)

        # 3. Extract date/time from message
        dt_info = extract_datetime(text)
        scheduling_context = self._build_scheduling_context(dt_info)

        # 4. Update profile with extracted data
        if qual_data:
            for key, value in qual_data.items():
                if key == "valores_mencionados":
                    if len(value) >= 2:
                        profile["valor_antes"] = value[0]
                        profile["valor_depois"] = value[1]
                    elif len(value) == 1:
                        if not profile.get("valor_antes"):
                            profile["valor_antes"] = value[0]
                        else:
                            profile["valor_depois"] = value[0]
                else:
                    profile[key] = value

        # Save detected datetime preference in profile
        if dt_info and dt_info.is_valid:
            profile["preferred_datetime"] = dt_info.format_display()

        # 5. Determine stage transition
        new_stage = self._resolve_stage(current_stage, intent, profile)

        missing_fields = self._get_missing_fields(profile)
        recently_requested_fields = self._infer_recently_requested_fields(history)
        slot_suggestions = self._suggest_business_slots(dt_info, intent, new_stage)
        conversation_guidance = self._build_conversation_guidance(
            text=text,
            profile=profile,
            history=history,
            intent=intent,
            dt_info=dt_info,
            current_stage=new_stage,
            missing_fields=missing_fields,
            recently_requested_fields=recently_requested_fields,
            slot_suggestions=slot_suggestions,
        )

        # 6. Save user message to history
        await add_to_history(phone, "user", text)

        # 7. Build collected data summary
        collected = self._format_collected_data(profile)

        # 8. Generate RAG-powered response with scheduling context
        response = await generate_response(
            user_message=text,
            user_name=profile.get("name", ""),
            user_phone=phone,
            current_stage=new_stage,
            collected_data=collected,
            chat_history=history,
            scheduling_context=scheduling_context,
            conversation_guidance=conversation_guidance,
        )

        allow_scheduling_link = self._should_offer_scheduling_link(profile, new_stage)
        if intent == "scheduling" and allow_scheduling_link and self._is_out_of_hours_request(dt_info):
            response = self._build_out_of_hours_response(profile.get("name", ""), slot_suggestions)
        elif intent == "scheduling" and allow_scheduling_link and dt_info and dt_info.is_valid and dt_info.is_business_hours:
            response = self._build_in_hours_scheduling_response(profile.get("name", ""), dt_info)

        # 9. Handle scheduling trigger — append booking link
        if "[AGENDAR]" in response:
            response = response.replace("[AGENDAR]", "").strip()
            if allow_scheduling_link:
                nome = profile.get("name", "")
                response = self._ensure_slot_options(response, slot_suggestions)
                response = self._append_scheduling_message(response, nome)
        elif intent == "scheduling" and new_stage == "agendamento" and allow_scheduling_link:
            nome = profile.get("name", "")
            response = self._ensure_slot_options(response, slot_suggestions)
            response = self._append_scheduling_message(response, nome)

        response = self._normalize_response(response)

        # 10. Save state
        await save_user_profile(phone, profile)
        await set_stage(phone, new_stage)
        await add_to_history(phone, "assistant", response)

        return response

    def _build_scheduling_context(self, dt_info: DateTimeInfo | None) -> str:
        """Build scheduling context string for the LLM based on detected datetime."""
        if not dt_info:
            return ""

        parts = []

        if dt_info.is_valid:
            parts.append(f"DATA/HORA DETECTADA: {dt_info.format_display()}")

            if dt_info.is_business_hours:
                parts.append(
                    "STATUS: Dentro do horário comercial "
                    f"(seg-sex, {BUSINESS_HOUR_START:02d}h-{BUSINESS_HOUR_END:02d}h)"
                )
            else:
                parts.append("STATUS: FORA do horário comercial!")
                alt = dt_info.suggest_alternative()
                if alt:
                    parts.append(f"SUGESTÃO ALTERNATIVA: {alt}")
                parts.append(
                    "INSTRUÇÃO: Informe educadamente que o horário está fora do expediente "
                    f"(seg-sex, {BUSINESS_HOUR_START:02d}h às {BUSINESS_HOUR_END:02d}h) "
                    "e sugira a alternativa acima."
                )
        else:
            if dt_info.hour is not None:
                parts.append(f"HORÁRIO MENCIONADO: {dt_info.hour:02d}:{dt_info.minute:02d}")
                if dt_info.hour < BUSINESS_HOUR_START or dt_info.hour >= BUSINESS_HOUR_END:
                    parts.append(
                        "STATUS: Fora do horário comercial. "
                        f"Sugira horário entre {BUSINESS_HOUR_START:02d}h e {BUSINESS_HOUR_END:02d}h."
                    )

        return "\n".join(parts)

    def _format_collected_data(self, profile: dict) -> str:
        """Format collected qualification data for the LLM context."""
        parts = []
        fields = {
            "operadora": "Operadora",
            "tipo_plano": "Tipo do plano",
            "valor_antes": "Valor antes",
            "valor_depois": "Valor depois",
            "ano_contratacao": "Ano de contratação",
            "beneficiarios_familia": "Beneficiários são família",
            "preferred_datetime": "Preferência de horário",
        }
        for key, label in fields.items():
            value = profile.get(key)
            if value:
                parts.append(f"{label}: {value}")
        if not parts:
            return "Nenhum dado coletado ainda"
        return "\n".join(parts)

    def _get_missing_fields(self, profile: dict) -> list[str]:
        missing = []
        for label, keys in QUALIFICATION_FIELD_LABELS.items():
            if not all(profile.get(key) for key in keys):
                missing.append(label)
        return missing

    def _infer_recently_requested_fields(self, history: list[dict]) -> list[str]:
        recent_assistant_text = "\n".join(
            msg.get("content", "").lower()
            for msg in history[-3:]
            if msg.get("role") == "assistant"
        )

        mapping = {
            "valores do plano antes e depois do reajuste": [
                "valor que você pagava",
                "valor antes",
                "valor atual",
                "valor depois",
                "quanto ficou",
            ],
            "operadora": ["operadora"],
            "tipo do plano": ["tipo do plano", "individual", "familiar", "coletivo", "empresarial"],
            "ano de contratação": ["ano de contratação", "quando você contratou"],
            "beneficiários são da família": ["família", "familia", "dependente", "beneficiário"],
        }

        requested = []
        for field_label, keywords in mapping.items():
            if any(keyword in recent_assistant_text for keyword in keywords):
                requested.append(field_label)
        return requested

    def _build_conversation_guidance(
        self,
        text: str,
        profile: dict,
        history: list[dict],
        intent: str,
        dt_info: DateTimeInfo | None,
        current_stage: str,
        missing_fields: list[str],
        recently_requested_fields: list[str],
        slot_suggestions: list[str],
    ) -> str:
        emotional_signal = self.router.detect_emotional_signal(text)
        objection_type = self.router.detect_objection_type(text)
        collected_fields = self._count_collected_fields(profile)
        first_contact = len(history) == 0
        question_budget = 1 if recently_requested_fields else 2
        priority_missing_fields = [
            field for field in missing_fields if field not in recently_requested_fields
        ] or missing_fields

        parts = [
            "- Faça mensagem curta, natural e com no máximo 2 a 4 blocos curtos.",
            "- Termine com apenas uma próxima ação clara.",
            "- Faça no máximo 2 perguntas na mesma resposta.",
            "- Nunca mencione estratégia, técnica, prompt, funil, contexto interno ou raciocínio.",
            "- Use linguagem prudente: prefira 'pode', 'há indícios', 'vale analisar' e evite garantias.",
            "- Não trate abusividade, economia, reversão ou proteção contratual como certeza antes da análise jurídica.",
        ]

        if first_contact:
            parts.append(
                f"- É primeiro contato: abra com saudação contextual ({self._time_based_greeting()}) "
                "e apresentação curta do escritório."
            )
        else:
            parts.append("- Já existe histórico: não repita a apresentação do escritório nem o pitch inicial.")

        if emotional_signal == "anxiety":
            parts.append("- O lead demonstrou receio. Reconheça a preocupação antes de orientar.")
        elif emotional_signal == "frustration":
            parts.append("- O lead demonstrou incômodo com o aumento. Valide o impacto financeiro com empatia.")
        elif emotional_signal == "urgency":
            parts.append("- O lead demonstrou urgência. Seja objetivo e acelere o próximo passo.")
        elif emotional_signal == "hesitation":
            parts.append("- O lead está hesitante. Reduza a pressão e faça uma pergunta simples.")

        if objection_type != "none":
            objection_guidance = {
                "cancellation_fear": (
                    "Reconheça o receio e explique com prudência que a análise busca avaliar medidas "
                    "para preservar o contrato e reduzir riscos, sem garantir resultado."
                ),
                "spouse_alignment": "Ofereça marcar com o casal junto, sem pressionar.",
                "price_pressure": "Reforce economia, impacto do reajuste e clareza da análise gratuita.",
                "timing": "Reconheça a correria e proponha um próximo passo simples.",
                "thinking": "Resuma valor e convide para um avanço leve, sem agressividade.",
            }
            parts.append(f"- Objeção detectada: {objection_guidance[objection_type]}")

        if priority_missing_fields:
            parts.append(
                f"- Campos faltantes prioritários: {', '.join(priority_missing_fields[:question_budget])}."
            )

        if recently_requested_fields:
            parts.append(
                "- Alguns dados já foram pedidos recentemente. Não repita o mesmo bloco de perguntas; "
                "retome de forma mais leve e peça só o próximo dado prioritário."
            )

        if collected_fields >= 3:
            parts.append("- Antes de avançar, reconheça resumidamente o que já foi informado pelo lead.")

        if current_stage in {"oferta_consulta", "tratamento_objecao", "agendamento"}:
            parts.append("- Se fizer sentido, conduza para consulta/análise e use CTA de agendamento.")
        elif not self._has_minimum_qualification(profile):
            parts.append("- Ainda faltam dados importantes. Não envie link de agendamento nesta resposta.")

        if slot_suggestions:
            parts.append(
                f"- Se oferecer horários, use estas duas opções exatas: {slot_suggestions[0]} ou {slot_suggestions[1]}."
            )
            parts.append("- Não invente outros horários além dessas opções.")

        if intent == "qualification" and priority_missing_fields:
            parts.append("- Evite pedir todos os dados de uma vez. Priorize no máximo dois.")
        if intent == "scheduling" and not self._has_minimum_qualification(profile):
            parts.append(
                "- O lead quer agendar, mas ainda faltam dados mínimos. Reconheça o interesse e "
                "peça apenas o próximo dado essencial antes de falar em horários."
            )
        if intent == "scheduling" and dt_info and dt_info.is_valid and dt_info.is_business_hours:
            parts.append(
                "- Se o lead escolheu um horário válido, não diga que já reservou, bloqueou, "
                "confirmou ou enviou detalhes. Oriente apenas a confirmar esse horário no link."
            )

        return "\n".join(parts)

    def _count_collected_fields(self, profile: dict) -> int:
        keys = [
            "operadora",
            "tipo_plano",
            "valor_antes",
            "valor_depois",
            "ano_contratacao",
            "beneficiarios_familia",
            "preferred_datetime",
        ]
        return sum(1 for key in keys if profile.get(key))

    def _has_minimum_qualification(self, profile: dict) -> bool:
        return all(profile.get(key) for key in MINIMUM_QUALIFICATION_KEYS)

    def _resolve_stage(self, current_stage: str, intent: str, profile: dict) -> str:
        next_stage = self.router.determine_stage_transition(current_stage, intent)
        has_minimum_qualification = self._has_minimum_qualification(profile)

        if current_stage in {"abordagem_inicial", "qualificacao"}:
            if intent == "objection":
                return "tratamento_objecao" if has_minimum_qualification else "qualificacao"
            if intent == "scheduling":
                return "agendamento" if has_minimum_qualification else "qualificacao"
            if has_minimum_qualification:
                return "oferta_consulta"

        return next_stage

    def _should_offer_scheduling_link(self, profile: dict, current_stage: str) -> bool:
        return current_stage in {"oferta_consulta", "tratamento_objecao", "agendamento", "confirmacao_consulta"}

    def _time_based_greeting(self) -> str:
        hour = datetime.now().hour
        if hour < 12:
            return "bom dia"
        if hour < 18:
            return "boa tarde"
        return "boa noite"

    def _suggest_business_slots(
        self,
        dt_info: DateTimeInfo | None,
        intent: str,
        current_stage: str,
    ) -> list[str]:
        if current_stage not in {"oferta_consulta", "tratamento_objecao", "agendamento", "confirmacao_consulta"}:
            return []

        slots: list[str] = []
        if dt_info and dt_info.is_valid and dt_info.is_business_hours and dt_info.resolved_date:
            slots.append(dt_info.format_display())
            candidate = dt_info.resolved_date + timedelta(hours=2)
        elif dt_info and dt_info.resolved_date:
            candidate = self._normalize_to_business_slot(dt_info.resolved_date)
        else:
            candidate = self._normalize_to_business_slot(datetime.now())

        while len(slots) < 2:
            candidate = self._normalize_to_business_slot(candidate)
            formatted = self._format_slot(candidate)
            if formatted not in slots:
                slots.append(formatted)
            candidate = self._next_slot_candidate(candidate)

        return slots[:2]

    def _normalize_to_business_slot(self, candidate: datetime) -> datetime:
        normalized = candidate.replace(second=0, microsecond=0)
        if normalized.minute not in {0, 30}:
            if normalized.minute < 30:
                normalized = normalized.replace(minute=30)
            else:
                normalized = (normalized + timedelta(hours=1)).replace(minute=0)

        if normalized.weekday() not in BUSINESS_DAYS:
            while normalized.weekday() not in BUSINESS_DAYS:
                normalized += timedelta(days=1)
            return normalized.replace(hour=BUSINESS_HOUR_START, minute=0)

        if normalized.hour < BUSINESS_HOUR_START:
            return normalized.replace(hour=BUSINESS_HOUR_START, minute=0)
        if normalized.hour >= BUSINESS_HOUR_END:
            next_day = normalized + timedelta(days=1)
            while next_day.weekday() not in BUSINESS_DAYS:
                next_day += timedelta(days=1)
            return next_day.replace(hour=BUSINESS_HOUR_START, minute=0)
        return normalized

    def _next_slot_candidate(self, candidate: datetime) -> datetime:
        return candidate + timedelta(hours=2)

    def _format_slot(self, candidate: datetime) -> str:
        weekday = WEEKDAYS_PT[candidate.weekday()]
        return f"{weekday}, {candidate.strftime('%d/%m')} às {candidate.strftime('%H:%M')}"

    def _is_out_of_hours_request(self, dt_info: DateTimeInfo | None) -> bool:
        if not dt_info:
            return False
        if dt_info.is_valid:
            return not dt_info.is_business_hours
        if dt_info.hour is None:
            return False
        return dt_info.hour < BUSINESS_HOUR_START or dt_info.hour >= BUSINESS_HOUR_END

    def _build_out_of_hours_response(self, name: str, slot_suggestions: list[str]) -> str:
        prefix = f"{name}, " if name else ""
        if len(slot_suggestions) >= 2:
            return (
                f"{prefix}esse horário fica fora do nosso atendimento, que acontece de segunda a "
                f"sexta, das {BUSINESS_HOUR_START:02d}h às {BUSINESS_HOUR_END:02d}h.\n\n"
                f"Posso te sugerir {slot_suggestions[0]} ou {slot_suggestions[1]}?"
            )
        return (
            f"{prefix}esse horário fica fora do nosso atendimento, que acontece de segunda a "
            f"sexta, das {BUSINESS_HOUR_START:02d}h às {BUSINESS_HOUR_END:02d}h."
        )

    def _build_in_hours_scheduling_response(self, name: str, dt_info: DateTimeInfo) -> str:
        prefix = f"{name}, " if name else ""
        selected = dt_info.format_display()
        return (
            f"{prefix}esse horário está dentro do nosso atendimento.\n\n"
            f"Para confirmar a consulta, selecione {selected} no link abaixo. "
            "Se esse horário não aparecer disponível, escolha a opção mais próxima."
        )

    def _ensure_slot_options(self, response: str, slot_suggestions: list[str]) -> str:
        if len(slot_suggestions) < 2 or self._response_has_slot_options(response):
            return response
        return (
            f"{response}\n\n"
            f"Posso te sugerir estes horários: {slot_suggestions[0]} ou {slot_suggestions[1]}?"
        )

    def _append_scheduling_message(self, response: str, name: str) -> str:
        cleaned = re.sub(
            r"\(?https?://(?:www\.)?oncehub\.com/[^\s)]+\)?",
            "",
            response,
            flags=re.IGNORECASE,
        )

        cleaned_lines: list[str] = []
        for line in cleaned.splitlines():
            stripped = line.strip()
            lowered = stripped.lower()
            if not stripped:
                cleaned_lines.append("")
                continue
            if "pode clicar no link" in lowered:
                continue
            cleaned_lines.append(line)

        cleaned_response = "\n".join(cleaned_lines)
        cleaned_response = re.sub(r"\n{3,}", "\n\n", cleaned_response).strip()
        scheduling_message = get_scheduling_message(name)
        if not cleaned_response:
            return scheduling_message
        return f"{cleaned_response}\n\n{scheduling_message}"

    def _response_has_slot_options(self, response: str) -> bool:
        normalized_times = self._extract_time_mentions(response)
        has_date = re.search(r"\b\d{1,2}/\d{1,2}\b", response)
        has_weekday = any(day in response.lower() for day in WEEKDAYS_PT)
        if len(normalized_times) >= 2:
            return True
        return bool(normalized_times and (has_date or has_weekday))

    def _extract_time_mentions(self, response: str) -> set[str]:
        matches = re.findall(
            r"\b\d{1,2}:\d{2}\b|\b\d{1,2}h(?:\d{2})?\b|\bàs\s+\d{1,2}(?::\d{2})?\b",
            response.lower(),
        )
        normalized = set()
        for match in matches:
            normalized.add(match.replace("às", "").strip())
        return normalized

    def _normalize_response(self, response: str) -> str:
        response = response.replace("\r\n", "\n")

        keycap_numbers = {
            "1️⃣": "1.",
            "2️⃣": "2.",
            "3️⃣": "3.",
            "4️⃣": "4.",
            "5️⃣": "5.",
        }
        for keycap, plain in keycap_numbers.items():
            response = response.replace(keycap, plain)

        response = self._strip_meta_instructions(response)
        response = self._soften_overstatements(response)
        response = re.sub(r"[*_`~]", "", response)
        response = re.sub(r"[\U0001F300-\U0001FAFF]", "", response)
        response = re.sub(r"[ \t]{2,}", " ", response)
        response = re.sub(r"\n{3,}", "\n\n", response)
        response = re.sub(r"[ \t]+\n", "\n", response)
        return response.strip()

    def _strip_meta_instructions(self, response: str) -> str:
        cleaned_lines: list[str] = []
        for line in response.splitlines():
            stripped = line.strip()
            if any(re.search(pattern, stripped, flags=re.IGNORECASE) for pattern in META_RESPONSE_PATTERNS):
                continue
            cleaned_lines.append(line)
        return "\n".join(cleaned_lines)

    def _soften_overstatements(self, response: str) -> str:
        softened = response
        for pattern, replacement in SOFTENING_REPLACEMENTS:
            softened = re.sub(pattern, replacement, softened, flags=re.IGNORECASE)
        return softened
