from http import HTTPStatus
from typing import Any, Optional, Union

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.field_55f8b0c6040a20_ba_811a08_eb_4d92b9c2_response_200 import (
    Field55F8B0C6040A20Ba811A08Eb4D92B9C2Response200,
)
from ...types import Response


def _get_kwargs() -> dict[str, Any]:
    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/fb/page/getTags",
    }

    return _kwargs


def _parse_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Optional[Field55F8B0C6040A20Ba811A08Eb4D92B9C2Response200]:
    if response.status_code == 200:
        response_200 = Field55F8B0C6040A20Ba811A08Eb4D92B9C2Response200.from_dict(response.json())

        return response_200
    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Response[Field55F8B0C6040A20Ba811A08Eb4D92B9C2Response200]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
) -> Response[Field55F8B0C6040A20Ba811A08Eb4D92B9C2Response200]:
    """***Limit:*** 100 queries per second

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Field55F8B0C6040A20Ba811A08Eb4D92B9C2Response200]
    """

    kwargs = _get_kwargs()

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
) -> Optional[Field55F8B0C6040A20Ba811A08Eb4D92B9C2Response200]:
    """***Limit:*** 100 queries per second

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Field55F8B0C6040A20Ba811A08Eb4D92B9C2Response200
    """

    return sync_detailed(
        client=client,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
) -> Response[Field55F8B0C6040A20Ba811A08Eb4D92B9C2Response200]:
    """***Limit:*** 100 queries per second

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Field55F8B0C6040A20Ba811A08Eb4D92B9C2Response200]
    """

    kwargs = _get_kwargs()

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
) -> Optional[Field55F8B0C6040A20Ba811A08Eb4D92B9C2Response200]:
    """***Limit:*** 100 queries per second

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Field55F8B0C6040A20Ba811A08Eb4D92B9C2Response200
    """

    return (
        await asyncio_detailed(
            client=client,
        )
    ).parsed
