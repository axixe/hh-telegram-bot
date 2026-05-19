import unittest

from bot.services.ai_dry_run_service import parse_ai_dry_run_logs


class AiDryRunServiceTest(unittest.TestCase):
    def test_parse_ai_dry_run_logs_counts_checked_rejected_and_skipped(self) -> None:
        stats = parse_ai_dry_run_logs(
            "\n".join(
                [
                    "time=\"2026\" level=warning msg=\"compose noise\"",
                    "🚀 Начинаю рассылку откликов для резюме: Frontend-разработчик",
                    "[D] AI (light) ответ (попытка 1): {\"suitable\": false}",
                    "🧠 AI (light) посчитал неподходящей https://hh.ru/vacancy/1",
                    "[D] AI (light) ответ (попытка 1): {\"suitable\": true}",
                    "[D] Пробуем откликнуться на вакансию: https://hh.ru/vacancy/3",
                    "⏩ Вакансия уже отклонена ранее https://hh.ru/vacancy/2",
                    "✅️ Закончили рассылку для резюме: Frontend-разработчик. Отправлено: 0",
                    "Container hh_applicant_tool_tg_123 Created",
                ]
            ),
            target_count=10,
            ai_filter="light",
        )

        self.assertEqual(stats.checked_count, 2)
        self.assertEqual(stats.ai_filter, "light")
        self.assertEqual(stats.rejected_count, 1)
        self.assertEqual(stats.suitable_count, 1)
        self.assertEqual(stats.already_rejected_count, 1)
        self.assertEqual(stats.rejected_urls, ("https://hh.ru/vacancy/1",))
        self.assertEqual(stats.approved_urls, ("https://hh.ru/vacancy/3",))
        self.assertEqual(stats.already_rejected_urls, ("https://hh.ru/vacancy/2",))
        self.assertEqual(stats.current_resume, "Frontend-разработчик")
        self.assertTrue(stats.is_finished)
        self.assertTrue(all("Container" not in event for event in stats.events))

    def test_parse_ai_dry_run_logs_counts_printed_ai_decisions_without_debug_answers(self) -> None:
        stats = parse_ai_dry_run_logs(
            "\n".join(
                [
                    "🧠 AI (heavy) посчитал неподходящей https://hh.ru/vacancy/1",
                    "🧠 AI (heavy) посчитал неподходящей https://hh.ru/vacancy/2",
                    "📨 Отправили отклик на вакансию https://hh.ru/vacancy/3",
                    "⏩ Вакансия уже отклонена ранее https://hh.ru/vacancy/4",
                ]
            ),
            target_count=10,
            ai_filter="heavy",
        )

        self.assertEqual(stats.checked_count, 3)
        self.assertEqual(stats.rejected_count, 2)
        self.assertEqual(stats.suitable_count, 1)
        self.assertEqual(stats.already_rejected_count, 1)
        self.assertEqual(stats.approved_urls, ("https://hh.ru/vacancy/3",))


if __name__ == "__main__":
    unittest.main()
