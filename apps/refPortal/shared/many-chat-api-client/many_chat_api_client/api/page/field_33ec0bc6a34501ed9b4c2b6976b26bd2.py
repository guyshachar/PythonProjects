from http import HTTPStatus
from typing import Any, Optional, Union

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.field_33_ec_0_bc_6a34501_ed_9b4c2b6976b26_bd_2_response_200 import (
    Field33Ec0Bc6A34501Ed9B4C2B6976B26Bd2Response200,
)
from ...types import Response


def _get_kwargs() -> dict[str, Any]:
    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/fb/page/getWidgets",
    }

    return _kwargs


def _parse_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Optional[Field33Ec0Bc6A34501Ed9B4C2B6976B26Bd2Response200]:
    if response.status_code == 200:
        response_200 = Field33Ec0Bc6A34501Ed9B4C2B6976B26Bd2Response200.from_dict(response.json())

        return response_200
    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Response[Field33Ec0Bc6A34501Ed9B4C2B6976B26Bd2Response200]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
) -> Response[Field33Ec0Bc6A34501Ed9B4C2B6976B26Bd2Response200]:
    """***Limit:*** 100 queries per second.<br>Use getGrowthTools instead.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Field33Ec0Bc6A34501Ed9B4C2B6976B26Bd2Response200]
    """

    kwargs = _get_kwargs()

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
) -> Optional[Field33Ec0Bc6A34501Ed9B4C2B6976B26Bd2Response200]:
    """***Limit:*** 100 queries per second.<br>Use getGrowthTools instead.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Field33Ec0Bc6A34501Ed9B4C2B6976B26Bd2Response200
    """

    return sync_detailed(
        client=client,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
) -> Response[Field33Ec0Bc6A34501Ed9B4C2B6976B26Bd2Response200]:
    """***Limit:*** 100 queries per second.<br>Use getGrowthTools instead.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Field33Ec0Bc6A34501Ed9B4C2B6976B26Bd2Response200]
    """

    kwargs = _get_kwargs()

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
) -> Optional[Field33Ec0Bc6A34501Ed9B4C2B6976B26Bd2Response200]:
    """***Limit:*** 100 queries per second.<br>Use getGrowthTools instead.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Field33Ec0Bc6A34501Ed9B4C2B6976B26Bd2Response200
    """

    return (
        await asyncio_detailed(
            client=client,
        )
    ).parsed
