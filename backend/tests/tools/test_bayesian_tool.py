import pytest
from src.tools.builtins.bayesian_inference import calculate_bayesian_risk


def test_calculate_bayesian_risk_with_symptoms():
    # Test with symptoms that should increase the probability of Management_Gap
    symptoms = ["CTO_departure", "R&D_drop"]
    prob = calculate_bayesian_risk.invoke({"symptoms": symptoms})

    assert isinstance(prob, float)
    assert prob > 0.0
    # With these symptoms, probability should be significantly higher than prior (0.2)
    assert prob > 0.5


def test_calculate_bayesian_risk_no_symptoms():
    # Test with no symptoms
    prob = calculate_bayesian_risk.invoke({"symptoms": []})

    assert isinstance(prob, float)
    # Should return the prior probability (approx 0.2)
    assert 0.19 < prob < 0.21


def test_calculate_bayesian_risk_unknown_symptoms():
    prob = calculate_bayesian_risk.invoke({"symptoms": ["Unknown_Symptom", "Another_One"]})

    assert isinstance(prob, float)
    assert 0.19 < prob < 0.21
