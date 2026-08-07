import unittest
from unittest.mock import AsyncMock, patch

from app.models.config import LLMConfig, SystemConfig
from app.services.config_service import ConfigService


class DeleteLLMConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_deletes_config_when_provider_is_a_string(self):
        service = ConfigService()
        config = SystemConfig(
            config_name="test",
            config_type="system",
            llm_configs=[
                LLMConfig(provider="deepseek", model_name="deepseek-chat"),
                LLMConfig(provider="deepseek", model_name="deepseek-reasoner"),
            ],
        )
        service.get_system_config = AsyncMock(return_value=config)
        service.save_system_config = AsyncMock(return_value=True)

        result = await service.delete_llm_config("DEEPSEEK", "deepseek-chat")

        self.assertTrue(result)
        self.assertEqual(
            [llm.model_name for llm in config.llm_configs],
            ["deepseek-reasoner"],
        )
        service.save_system_config.assert_awaited_once_with(config)

    async def test_clears_references_only_after_last_same_named_config_is_deleted(self):
        service = ConfigService()
        config = SystemConfig(
            config_name="test",
            config_type="system",
            llm_configs=[
                LLMConfig(provider="deepseek", model_name="shared-model"),
                LLMConfig(provider="openrouter", model_name="shared-model"),
            ],
            default_llm="shared-model",
            system_settings={
                "quick_analysis_model": "shared-model",
                "deep_analysis_model": "shared-model",
            },
        )
        service.get_system_config = AsyncMock(return_value=config)
        service.save_system_config = AsyncMock(return_value=True)

        self.assertTrue(
            await service.delete_llm_config("deepseek", "shared-model")
        )
        self.assertEqual(config.default_llm, "shared-model")
        self.assertEqual(config.system_settings["quick_analysis_model"], "shared-model")

        self.assertTrue(
            await service.delete_llm_config("openrouter", "shared-model")
        )
        self.assertIsNone(config.default_llm)
        self.assertEqual(config.system_settings["quick_analysis_model"], "")
        self.assertEqual(config.system_settings["deep_analysis_model"], "")

    async def test_update_uses_provider_and_model_name_as_identity(self):
        service = ConfigService()
        config = SystemConfig(
            config_name="test",
            config_type="system",
            llm_configs=[
                LLMConfig(
                    provider="deepseek", model_name="shared-model", max_tokens=1000
                ),
                LLMConfig(
                    provider="openrouter", model_name="shared-model", max_tokens=2000
                ),
            ],
        )
        service.get_system_config = AsyncMock(return_value=config)
        service.save_system_config = AsyncMock(return_value=True)
        updated = LLMConfig(
            provider="openrouter", model_name="shared-model", max_tokens=3000
        )

        with patch(
            "app.services.config_service.unified_config.save_llm_config",
            return_value=True,
        ):
            result = await service.update_llm_config(updated)

        self.assertTrue(result)
        self.assertEqual(config.llm_configs[0].max_tokens, 1000)
        self.assertEqual(config.llm_configs[1].max_tokens, 3000)


if __name__ == "__main__":
    unittest.main()
