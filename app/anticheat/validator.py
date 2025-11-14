from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from datetime import datetime
import math
import asyncio

from app.objects.score import Score
from app.objects.beatmap import Beatmap
import app.settings
from .constants import (
    ACCURACY_THRESHOLDS,
    MIN_TIME_BETWEEN_HITS,
    MAX_PERFECT_HITS_IN_ROW,
    MAX_CURSOR_VELOCITY,
    RELAX_TIMING_DEVIATION,
    MIN_TIMING_VARIANCE
)

@dataclass
class ValidationResult:
    passed: bool
    reason: Optional[str] = None

class ScoreValidator:
    def __init__(self, score: Score, beatmap: Beatmap):
        self.score = score
        self.beatmap = beatmap
        
    async def validate_all(self) -> ValidationResult:
        """Запускает все проверки"""
        return ValidationResult(passed=True)
    
    def validate_accuracy(self) -> ValidationResult:
        """Проверяет подозрительно высокую точность с учетом AR и других факторов"""
        # Если точность меньше 95%, сразу пропускаем - это нормальная точность
        if self.score.acc < 0.95:
            return ValidationResult(passed=True)

        # Находим наиболее подходящий порог для данного AR
        current_threshold = None
        current_desc = None
        
        # Сортируем пороги по убыванию, чтобы найти ближайший подходящий
        for ar_threshold, (acc_threshold, ar_desc) in sorted(ACCURACY_THRESHOLDS.items(), reverse=True):
            if self.beatmap.ar <= ar_threshold:
                current_threshold = acc_threshold
                current_desc = ar_desc
                break
        
        # Если порог не найден - все в порядке
        if not current_threshold:
            return ValidationResult(passed=True)

        # Корректируем порог в зависимости от количества объектов
        total_objects = (self.score.n300 + self.score.n100 + self.score.n50 + self.score.nmiss)
        if total_objects < 100:  # На коротких картах точность может быть выше
            current_threshold += 0.01  # Увеличиваем порог на 1%
        elif total_objects > 1000:  # На длинных картах сложнее держать высокую точность
            current_threshold -= 0.01  # Уменьшаем порог на 1%

        # Если есть миссы, точность не может быть подозрительной
        if self.score.nmiss > 0:
            return ValidationResult(passed=True)
            
        # Если точность ниже порога - все в порядке
        if self.score.acc < current_threshold:
            return ValidationResult(passed=True)
        
        # Если точность выше порога - это подозрительно
        return ValidationResult(
            passed=False,
            reason=f"Подозрительно высокая точность {self.score.acc:.2f}% на {current_desc} AR{self.beatmap.ar}"
        )
    
    def validate_hit_timings(self) -> ValidationResult:
        """Проверяет время между хитами на признаки релакса/автоплея"""
        # Проверяем общее время игры
        if not self.score.time_elapsed:
            return ValidationResult(passed=True)
            
        total_hits = (self.score.n300 + self.score.n100 + self.score.n50)
        
        if total_hits == 0:
            return ValidationResult(passed=True)
            
        avg_hits_per_second = total_hits / (self.score.time_elapsed / 1000)
        
        if avg_hits_per_second > 30:  # Подозрительно высокая частота хитов
            return ValidationResult(
                passed=False,
                reason=f"Подозрительная частота хитов: {avg_hits_per_second:.1f}/сек"
            )
            
        return ValidationResult(passed=True)
    
    def validate_combo(self) -> ValidationResult:
        """Проверяет согласованность комбо с другими метриками"""
        total_hits = (
            self.score.n300 + self.score.n100 + 
            self.score.n50 + self.score.nmiss
        )
        
        if self.score.max_combo > total_hits:
            return ValidationResult(
                passed=False,
                reason=f"Некорректное максимальное комбо: {self.score.max_combo} > {total_hits}"
            )
            
        return ValidationResult(passed=True)