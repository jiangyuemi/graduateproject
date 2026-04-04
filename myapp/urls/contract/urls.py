from django.urls import path
from ...views.contract import ContractView

urlpatterns = [
    path('', ContractView.as_view(), name='contract_list'),
    path('<uuid:contract_id>/', ContractView.as_view(), name='contract_detail'),
]