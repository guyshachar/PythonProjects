from http import HTTPStatus
from typing import Any, Optional, Union

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.ae_51a27b65b7_ecf_39438_af_38_db_0f27_ba_response_200 import Ae51A27B65B7Ecf39438Af38Db0F27BaResponse200
from ...types import UNSET, Response


def _get_kwargs(
    *,
    subscriber_id: int,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    params["subscriber_id"] = subscriber_id

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/fb/subscriber/getInfo",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Optional[Ae51A27B65B7Ecf39438Af38Db0F27BaResponse200]:
    if response.status_code == 200:
        response_200 = Ae51A27B65B7Ecf39438Af38Db0F27BaResponse200.from_dict(response.json())

        return response_200
    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Response[Ae51A27B65B7Ecf39438Af38Db0F27BaResponse200]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    subscriber_id: int,
) -> Response[Ae51A27B65B7Ecf39438Af38Db0F27BaResponse200]:
    """***Limit:*** 10 queries per second

    Args:
        subscriber_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Ae51A27B65B7Ecf39438Af38Db0F27BaResponse200]
    """

    kwargs = _get_kwargs(
        subscriber_id=subscriber_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    subscriber_id: int,
) -> Optional[Ae51A27B65B7Ecf39438Af38Db0F27BaResponse200]:
    """***Limit:*** 10 queries per second

    Args:
        subscriber_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Ae51A27B65B7Ecf39438Af38Db0F27BaResponse200
    """

    return sync_detailed(
        client=client,
        subscriber_id=subscriber_id,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    subscriber_id: int,
) -> Response[Ae51A27B65B7Ecf39438Af38Db0F27BaResponse200]:
    """***Limit:*** 10 queries per second

    Args:
        subscriber_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Ae51A27B65B7Ecf39438Af38Db0F27BaResponse200]
    """

    kwargs = _get_kwargs(
        subscriber_id=subscriber_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    subscriber_id: int,
) -> Optional[Ae51A27B65B7Ecf39438Af38Db0F27BaResponse200]:
    """***Limit:*** 10 queries per second

    Args:
        subscriber_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Ae51A27B65B7Ecf39438Af38Db0F27BaResponse200
    """

    return (
        await asyncio_detailed(
            client=client,
            subscriber_id=subscriber_id,
        )
    ).parsed
