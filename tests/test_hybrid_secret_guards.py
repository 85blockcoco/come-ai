"""Fictitious credentials must never pass through public model metadata."""
import pytest

from devkit.evolution_providers import ProviderSettings, ProviderUnavailable
from devkit.exporting import KitError, validate_source_text
from usage_ledger import redact_text
from workspace_core import safe_error


@pytest.mark.parametrize("token", ["AQ." + "x" * 45, "sk-or-v1-" + "a" * 64, "AIza" + "y" * 35])
def test_credential_shaped_model_is_rejected_without_value(token):
    with pytest.raises(ProviderUnavailable) as caught:
        ProviderSettings(provider="ollama", model=token)
    assert token not in str(caught.value)
    assert token not in redact_text(token)
    with pytest.raises(KitError) as caught:
        validate_source_text(token)
    assert token not in str(caught.value)


def test_new_google_key_shape_is_masked_in_errors():
    token = "AQ." + "x" * 45
    assert token not in safe_error(RuntimeError("failure " + token))


def test_cpu_local_timeout_can_be_longer_without_relaxing_cloud():
    assert ProviderSettings(provider="ollama", model="qwen3.5:2b-q4_K_M", timeout_seconds=180).timeout_seconds == 180
    with pytest.raises(ProviderUnavailable):
        ProviderSettings(provider="gemini", model="gemini-3.8-flash", timeout_seconds=180)
