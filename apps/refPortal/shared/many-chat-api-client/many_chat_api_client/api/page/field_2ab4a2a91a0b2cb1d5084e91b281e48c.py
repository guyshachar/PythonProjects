from http import HTTPStatus
from typing import Any, Optional, Union

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.field_2_ab_4a2a91a0b2_cb_1d5084e91b281e48c_response_200 import (
    Field2Ab4A2A91A0B2Cb1D5084E91B281E48CResponse200,
)
from ...types import Response


def _get_kwargs() -> dict[str, Any]:
    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/fb/page/getGrowthTools",
    }

    return _kwargs


def _parse_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Optional[Field2Ab4A2A91A0B2Cb1D5084E91B281E48CResponse200]:
    if response.status_code == 200:
        response_200 = Field2Ab4A2A91A0B2Cb1D5084E91B281E48CResponse200.from_dict(response.json())

        return response_200
    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Response[Field2Ab4A2A91A0B2Cb1D5084E91B281E48CResponse200]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
) -> Response[Field2Ab4A2A91A0B2Cb1D5084E91B281E48CResponse200]:
    """***Limit:*** 100 queries per second

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Field2Ab4A2A91A0B2Cb1D5084E91B281E48CResponse200]
    """

    kwargs = _get_kwargs()

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
) -> Optional[Field2Ab4A2A91A0B2Cb1D5084E91B281E48CResponse200]:
    """***Limit:*** 100 queries per second

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Field2Ab4A2A91A0B2Cb1D5084E91B281E48CResponse200
    """

    return sync_detailed(
        client=client,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
) -> Response[Field2Ab4A2A91A0B2Cb1D5084E91B281E48CResponse200]:
    """***Limit:*** 100 queries per second

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Field2Ab4A2A91A0B2Cb1D5084E91B281E48CResponse200]
    """

    kwargs = _get_kwargs()

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
) -> Optional[Field2Ab4A2A91A0B2Cb1D5084E91B281E48CResponse200]:
    """***Limit:*** 100 queries per second

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Field2Ab4A2A91A0B2Cb1D5084E91B281E48CResponse200
    """

    return (
        await asyncio_detailed(
            client=client,
        )
    ).parsed
