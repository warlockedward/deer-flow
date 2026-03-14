from pgmpy.models import DiscreteBayesianNetwork
from pgmpy.factors.discrete import TabularCPD
from pgmpy.inference import VariableElimination
from langchain.tools import tool

MANAGEMENT_GAP = "Management_Gap"
CTO_DEPARTURE = "CTO_departure"
RD_DROP = "R&D_drop"

KNOWN_SYMPTOMS = {CTO_DEPARTURE, RD_DROP}

model = DiscreteBayesianNetwork([(MANAGEMENT_GAP, CTO_DEPARTURE), (MANAGEMENT_GAP, RD_DROP)])

cpd_mg = TabularCPD(variable=MANAGEMENT_GAP, variable_card=2, values=[[0.8], [0.2]])

cpd_cd = TabularCPD(variable=CTO_DEPARTURE, variable_card=2, values=[[0.9, 0.3], [0.1, 0.7]], evidence=[MANAGEMENT_GAP], evidence_card=[2])

cpd_rd = TabularCPD(variable=RD_DROP, variable_card=2, values=[[0.8, 0.2], [0.2, 0.8]], evidence=[MANAGEMENT_GAP], evidence_card=[2])

model.add_cpds(cpd_mg, cpd_cd, cpd_rd)
infer = VariableElimination(model)


@tool("calculate_bayesian_risk", parse_docstring=True)
def calculate_bayesian_risk(symptoms: list[str]) -> float:
    """Calculate the probability of a Management Gap given observed symptoms.

    Args:
        symptoms: A list of observed symptoms (e.g., ["CTO_departure", "R&D_drop"]).
    """
    evidence = {}
    for symptom in symptoms:
        if symptom in KNOWN_SYMPTOMS:
            evidence[symptom] = 1

    result = infer.query(variables=[MANAGEMENT_GAP], evidence=evidence)
    return float(result.values[1])


def update_priors():
    """Stub for RLHF hook to update model priors."""
    pass
