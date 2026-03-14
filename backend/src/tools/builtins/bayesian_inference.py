from pgmpy.models import DiscreteBayesianNetwork
from pgmpy.factors.discrete import TabularCPD
from pgmpy.inference import VariableElimination
from langchain.tools import tool

model = DiscreteBayesianNetwork([("Management_Gap", "CTO_departure"), ("Management_Gap", "R&D_drop")])

cpd_mg = TabularCPD(variable="Management_Gap", variable_card=2, values=[[0.8], [0.2]])

cpd_cd = TabularCPD(variable="CTO_departure", variable_card=2, values=[[0.9, 0.3], [0.1, 0.7]], evidence=["Management_Gap"], evidence_card=[2])

cpd_rd = TabularCPD(variable="R&D_drop", variable_card=2, values=[[0.8, 0.2], [0.2, 0.8]], evidence=["Management_Gap"], evidence_card=[2])

model.add_cpds(cpd_mg, cpd_cd, cpd_rd)
infer = VariableElimination(model)


@tool("calculate_bayesian_risk", parse_docstring=True)
def calculate_bayesian_risk(symptoms: list[str]) -> float:
    """Calculate the probability of a Management Gap given observed symptoms.

    Args:
        symptoms: A list of observed symptoms (e.g., ["CTO_departure", "R&D_drop"]).
    """
    evidence = {}
    if "CTO_departure" in symptoms:
        evidence["CTO_departure"] = 1
    if "R&D_drop" in symptoms:
        evidence["R&D_drop"] = 1

    result = infer.query(variables=["Management_Gap"], evidence=evidence)
    return float(result.values[1])


def update_priors():
    """Stub for RLHF hook to update model priors."""
    pass
