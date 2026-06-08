from http import HTTPStatus
from typing import Any, Optional, Union

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.b14c21e0143_af_0449_cfc_94e58731c5a8_body import B14C21E0143Af0449Cfc94E58731C5A8Body
from ...models.b14c21e0143_af_0449_cfc_94e58731c5a8_response_200 import B14C21E0143Af0449Cfc94E58731C5A8Response200
from ...types import Response


def _get_kwargs(
    *,
    body: B14C21E0143Af0449Cfc94E58731C5A8Body,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/fb/subscriber/verifyBySignedRequest",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Optional[B14C21E0143Af0449Cfc94E58731C5A8Response200]:
    if response.status_code == 200:
        response_200 = B14C21E0143Af0449Cfc94E58731C5A8Response200.from_dict(response.json())

        return response_200
    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Response[B14C21E0143Af0449Cfc94E58731C5A8Response200]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: B14C21E0143Af0449Cfc94E58731C5A8Body,
) -> Response[B14C21E0143Af0449Cfc94E58731C5A8Response200]:
    """***Limit:*** 10 queries per second

    Args:
        body (B14C21E0143Af0449Cfc94E58731C5A8Body):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[B14C21E0143Af0449Cfc94E58731C5A8Response200]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: B14C21E0143Af0449Cfc94E58731C5A8Body,
) -> Optional[B14C21E0143Af0449Cfc94E58731C5A8Response200]:
    """***Limit:*** 10 queries per second

    Args:
        body (B14C21E0143Af0449Cfc94E58731C5A8Body):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        B14C21E0143Af0449Cfc94E58731C5A8Response200
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: B14C21E0143Af0449Cfc94E58731C5A8Body,
) -> Response[B14C21E0143Af0449Cfc94E58731C5A8Response200]:
    """***Limit:*** 10 queries per second

    Args:
        body (B14C21E0143Af0449Cfc94E58731C5A8Body):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[B14C21E0143Af0449Cfc94E58731C5A8Response200]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: B14C21E0143Af0449Cfc94E58731C5A8Body,
) -> Optional[B14C21E0143Af0449Cfc94E58731C5A8Response200]:
    """***Limit:*** 10 queries per second

    Args:
        body (B14C21E0143Af0449Cfc94E58731C5A8Body):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        B14C21E0143Af0449Cfc94E58731C5A8Response200
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
