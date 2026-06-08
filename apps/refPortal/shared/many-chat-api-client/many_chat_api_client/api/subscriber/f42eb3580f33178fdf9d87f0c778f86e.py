from http import HTTPStatus
from typing import Any, Optional, Union

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.f42_eb_3580f33178_fdf_9d87f0c778f86e_body import F42Eb3580F33178Fdf9D87F0C778F86EBody
from ...models.f42_eb_3580f33178_fdf_9d87f0c778f86e_response_200 import F42Eb3580F33178Fdf9D87F0C778F86EResponse200
from ...models.response_error import ResponseError
from ...types import Response


def _get_kwargs(
    *,
    body: F42Eb3580F33178Fdf9D87F0C778F86EBody,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/fb/subscriber/createSubscriber",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Optional[Union[F42Eb3580F33178Fdf9D87F0C778F86EResponse200, ResponseError]]:
    if response.status_code == 200:
        response_200 = F42Eb3580F33178Fdf9D87F0C778F86EResponse200.from_dict(response.json())

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
) -> Response[Union[F42Eb3580F33178Fdf9D87F0C778F86EResponse200, ResponseError]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: F42Eb3580F33178Fdf9D87F0C778F86EBody,
) -> Response[Union[F42Eb3580F33178Fdf9D87F0C778F86EResponse200, ResponseError]]:
    """Create a Unified subscriber

     ***Limit:*** 10 queries per second

    Args:
        body (F42Eb3580F33178Fdf9D87F0C778F86EBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Union[F42Eb3580F33178Fdf9D87F0C778F86EResponse200, ResponseError]]
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
    body: F42Eb3580F33178Fdf9D87F0C778F86EBody,
) -> Optional[Union[F42Eb3580F33178Fdf9D87F0C778F86EResponse200, ResponseError]]:
    """Create a Unified subscriber

     ***Limit:*** 10 queries per second

    Args:
        body (F42Eb3580F33178Fdf9D87F0C778F86EBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Union[F42Eb3580F33178Fdf9D87F0C778F86EResponse200, ResponseError]
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: F42Eb3580F33178Fdf9D87F0C778F86EBody,
) -> Response[Union[F42Eb3580F33178Fdf9D87F0C778F86EResponse200, ResponseError]]:
    """Create a Unified subscriber

     ***Limit:*** 10 queries per second

    Args:
        body (F42Eb3580F33178Fdf9D87F0C778F86EBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Union[F42Eb3580F33178Fdf9D87F0C778F86EResponse200, ResponseError]]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: F42Eb3580F33178Fdf9D87F0C778F86EBody,
) -> Optional[Union[F42Eb3580F33178Fdf9D87F0C778F86EResponse200, ResponseError]]:
    """Create a Unified subscriber

     ***Limit:*** 10 queries per second

    Args:
        body (F42Eb3580F33178Fdf9D87F0C778F86EBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Union[F42Eb3580F33178Fdf9D87F0C778F86EResponse200, ResponseError]
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
