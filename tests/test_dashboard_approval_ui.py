from mas.api.server import DASHBOARD_HTML


def test_dashboard_contains_approval_inbox_ui():
    assert 'section-approvals' in DASHBOARD_HTML
    assert 'approval-box' in DASHBOARD_HTML
    assert "/api/approvals/pending" in DASHBOARD_HTML
    assert "/api/approvals/${action}" in DASHBOARD_HTML
    assert "approvalAction('approve')" in DASHBOARD_HTML
    assert "approvalAction('reject')" in DASHBOARD_HTML
