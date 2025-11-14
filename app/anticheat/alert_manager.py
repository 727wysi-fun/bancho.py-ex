from __future__ import annotations

import time
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta

from app.objects.score import Score
from app.discord import Embed, Webhook
import app.settings
from app.logging import Ansi, log

class AlertManager:
    _instance = None
    _alerts: Dict[int, Dict[str, Tuple[datetime, int]]] = {}  # player_id -> {reason -> (last_alert_time, count)}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AlertManager, cls).__new__(cls)
        return cls._instance
    
    async def send_alert(self, score: Score, reason: str, evidence: dict | None = None) -> bool:
        """
        Отправляет уведомление о подозрительном скоре с защитой от спама.
        Возвращает True если уведомление было отправлено, False если было отфильтровано.
        """
        # Античит вебхук отключен
        return False
            
        # Проверяем, не было ли недавно похожих уведомлений
        now = datetime.now()
        player_alerts = self._alerts.setdefault(score.player.id, {})
        
        if reason in player_alerts:
            last_time, count = player_alerts[reason]
            if now - last_time < timedelta(minutes=5):  # Окно в 5 минут
                if count >= 3:  # Максимум 3 похожих уведомления за 5 минут
                    return False
                player_alerts[reason] = (last_time, count + 1)
            else:
                player_alerts[reason] = (now, 1)
        else:
            player_alerts[reason] = (now, 1)

        # Формируем описание
        description = (
            f"Игрок: [{score.player.name}](https://{app.settings.DOMAIN}/u/{score.player.id})\n"
            f"Карта: {score.bmap.full_name}\n"
            f"Мод(ы): {score.mods!r}\n"
        )
        
        if hasattr(score, 'pp'):
            description += f"PP: {score.pp:.2f}\n"
            
        description += (
            f"Точность: {score.acc:.2f}%\n"
            f"Максимальное комбо: {score.max_combo}x"
        )
        
        # Добавляем ссылку на скор только если есть ID
        if score.id is not None:
            description += f"\nСсылка на скор: https://{app.settings.DOMAIN}/s/{score.id}"

        embed = Embed(
            title="⚠️ Подозрительный скор обнаружен",
            description=description,
            color=0xFF0000
        )

        embed.add_field(
            name="Причина подозрения",
            value=reason,
            inline=False
        )

        if evidence:
            evidence_text = "\n".join(f"- {k}: {v}" for k, v in evidence.items())
            embed.add_field(
                name="Подробности",
                value=f"```\n{evidence_text}\n```",
                inline=False
            )

        embed.set_thumbnail(url=f"https://a.{app.settings.DOMAIN}/{score.player.id}")
        
        webhook = Webhook(url=app.settings.ANTICHEAT_WEBHOOK)
        webhook.add_embed(embed)
        
        try:
            await webhook.post()
            log(f"Отправлено уведомление античита для {score.player.name}", Ansi.LGREEN)
            return True
        except Exception as e:
            log(f"Ошибка отправки уведомления античита: {e}", Ansi.LRED)
            return False

# Глобальный экземпляр для использования во всем приложении
alert_manager = AlertManager()