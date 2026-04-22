# karma/views.py
import json
import time

from django.contrib.auth import get_user_model
from django.db.models import Sum, Value
from django.db.models.functions import Coalesce
from django.http import StreamingHttpResponse
from django.shortcuts import render

from karma.services import get_balance

User = get_user_model()

LEADERBOARD_SIZE = 20
STREAM_INTERVAL_SECONDS = 10


def _leaderboard_rows(search=''):
    qs = (
        User.objects.annotate(
            karma=Coalesce(Sum('karma_transactions__delta'), Value(0))
        )
        .filter(karma__gt=0)
        .order_by('-karma')
    )
    if search:
        qs = qs.filter(username__icontains=search)

    rows = []
    for rank, user in enumerate(qs[:LEADERBOARD_SIZE], start=1):
        rows.append({
            'rank': rank,
            'username': user.username,
            'karma': user.karma,
        })
    return rows


def leaderboard(request):
    search = (request.GET.get('q') or '').strip()
    rows = _leaderboard_rows(search)
    return render(request, 'karma/leaderboard.html', {
        'rows': rows,
        'search': search,
        'leaderboard_size': LEADERBOARD_SIZE,
    })


def leaderboard_stream(request):
    """SSE endpoint — pushes fresh leaderboard JSON every STREAM_INTERVAL_SECONDS."""

    def event_stream():
        while True:
            rows = _leaderboard_rows()
            data = json.dumps(rows)
            yield f'data: {data}\n\n'
            time.sleep(STREAM_INTERVAL_SECONDS)

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response
