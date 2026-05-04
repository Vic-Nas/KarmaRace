# karma/views.py
import asyncio
import json

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render

from karma.services import get_balance

User = get_user_model()

LEADERBOARD_SIZE       = 10
STREAM_INTERVAL_SECONDS = 10


def _leaderboard_rows(search=''):
    qs = (
        User.objects
        .annotate(karma=Coalesce(Sum('karma_transactions__delta'), Value(0)))
        .filter(karma__gt=0)
        .order_by('-karma')
    )
    if search:
        qs = qs.filter(username__icontains=search)
    return [
        {'rank': rank, 'username': user.username, 'karma': user.karma}
        for rank, user in enumerate(qs[:LEADERBOARD_SIZE], start=1)
    ]


@login_required
def balance(request):
    """API endpoint to get current user's karma balance."""
    return JsonResponse({'balance': get_balance(request.user)})


def leaderboard(request):
    search = (request.GET.get('q') or '').strip()
    return render(request, 'karma/leaderboard.html', {
        'rows':   _leaderboard_rows(search),
        'search': search,
    })


async def leaderboard_stream(request):
    """SSE; pushes fresh top-10 JSON every STREAM_INTERVAL_SECONDS."""
    _leaderboard_rows_async = sync_to_async(_leaderboard_rows)

    async def event_stream():
        while True:
            rows = await _leaderboard_rows_async()
            yield f'data: {json.dumps(rows)}\n\n'
            await asyncio.sleep(STREAM_INTERVAL_SECONDS)

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control']     = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response