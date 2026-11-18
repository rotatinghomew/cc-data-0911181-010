from . import recommendations
from . import pilot_funds
from . import pilot_agreements

OPERATIONS={
    'recommendations.propose':recommendations.propose,
    'pilot_funds.approve':pilot_funds.approve,
    'pilot_agreements.sign':pilot_agreements.sign,
    'pilot_agreements.audit':pilot_agreements.audit,
}
