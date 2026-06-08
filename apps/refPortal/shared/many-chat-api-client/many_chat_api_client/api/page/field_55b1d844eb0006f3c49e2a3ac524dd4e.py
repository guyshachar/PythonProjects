from http import HTTPStatus
from typing import Any, Optional, Union

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.field_55b1d844_eb_0006f3c49e2a3_ac_524_dd_4e_body import Field55B1D844Eb0006F3C49E2A3Ac524Dd4EBody
from ...models.field_55b1d844_eb_0006f3c49e2a3_ac_524_dd_4e_response_200 import (
    Field55B1D844Eb0006F3C49E2A3Ac524Dd4EResponse200,
)
from ...models.response_error import ResponseError
from ...types import Response


def _get_kwargs(
    *,
    body: Field55B1D844Eb0006F3C49E2A3Ac524Dd4EBody,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/fb/page/removeTag",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Optional[Union[Field55B1D844Eb0006F3C49E2A3Ac524Dd4EResponse200, ResponseError]]:
    if response.status_code == 200:
        response_200 = Field55B1D844Eb0006F3C49E2A3Ac524Dd4EResponse200.from_dict(response.json())

        return response_200
    if response.status_code == 400:
        response_400 = ResponseError.from_dict(response.json())

        return response_400
    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Response[Union[Field55B1D844Eb0006F3C49E2A3Ac524Dd4EResponse200, ResponseError]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: Field55B1D844Eb0006F3C49E2A3Ac524Dd4EBody,
) -> Response[Union[Field55B1D844Eb0006F3C49E2A3Ac524Dd4EResponse200, ResponseError]]:
    """***Limit:*** 10 queries per second.<br>Removes specified tag from the page and the page's
    subscribers.<br>This action can not be undone.

    Args:
        body (Field55B1D844Eb0006F3C49E2A3Ac524Dd4EBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Union[Field55B1D844Eb0006F3C49E2A3Ac524Dd4EResponse200, ResponseError]]
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
    body: Field55B1D844Eb0006F3C49E2A3Ac524Dd4EBody,
) -> Optional[Union[Field55B1D844Eb0006F3C49E2A3Ac524Dd4EResponse200, ResponseError]]:
    """***Limit:*** 10 queries per second.<br>Removes specified tag from the page and the page's
    subscribers.<br>This action can not be undone.

    Args:
        body (Field55B1D844Eb0006F3C49E2A3Ac524Dd4EBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Union[Field55B1D844Eb0006F3C49E2A3Ac524Dd4EResponse200, ResponseError]
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: Field55B1D844Eb0006F3C49E2A3Ac524Dd4EBody,
) -> Response[Union[Field55B1D844Eb0006F3C49E2A3Ac524Dd4EResponse200, ResponseError]]:
    """***Limit:*** 10 queries per second.<br>Removes specified tag from the page and the page's
    subscribers.<br>This action can not be undone.

    Args:
        body (Field55B1D844Eb0006F3C49E2A3Ac524Dd4EBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Union[Field55B1D844Eb0006F3C49E2A3Ac524Dd4EResponse200, ResponseError]]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: Field55B1D844Eb0006F3C49E2A3Ac524Dd4EBody,
) -> Optional[Union[Field55B1D844Eb0006F3C49E2A3Ac524Dd4EResponse200, ResponseError]]:
    """***Limit:*** 10 queries per second.<br>Removes specified tag from the page and the page's
    subscribers.<br>This action can not be undone.

    Args:
        body (Field55B1D844Eb0006F3C49E2A3Ac524Dd4EBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Union[Field55B1D844Eb0006F3C49E2A3Ac524Dd4EResponse200, ResponseError]
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
