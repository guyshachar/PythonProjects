from http import HTTPStatus
from typing import Any, Optional, Union

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.e964547412_ede_512f9534970c8e3971a_body import E964547412Ede512F9534970C8E3971ABody
from ...models.e964547412_ede_512f9534970c8e3971a_response_200 import E964547412Ede512F9534970C8E3971AResponse200
from ...models.response_error import ResponseError
from ...types import Response


def _get_kwargs(
    *,
    body: E964547412Ede512F9534970C8E3971ABody,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/fb/page/createTag",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Optional[Union[E964547412Ede512F9534970C8E3971AResponse200, ResponseError]]:
    if response.status_code == 200:
        response_200 = E964547412Ede512F9534970C8E3971AResponse200.from_dict(response.json())

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
) -> Response[Union[E964547412Ede512F9534970C8E3971AResponse200, ResponseError]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: E964547412Ede512F9534970C8E3971ABody,
) -> Response[Union[E964547412Ede512F9534970C8E3971AResponse200, ResponseError]]:
    """***Limit:*** 10 queries per second

    Args:
        body (E964547412Ede512F9534970C8E3971ABody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Union[E964547412Ede512F9534970C8E3971AResponse200, ResponseError]]
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
    body: E964547412Ede512F9534970C8E3971ABody,
) -> Optional[Union[E964547412Ede512F9534970C8E3971AResponse200, ResponseError]]:
    """***Limit:*** 10 queries per second

    Args:
        body (E964547412Ede512F9534970C8E3971ABody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Union[E964547412Ede512F9534970C8E3971AResponse200, ResponseError]
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: E964547412Ede512F9534970C8E3971ABody,
) -> Response[Union[E964547412Ede512F9534970C8E3971AResponse200, ResponseError]]:
    """***Limit:*** 10 queries per second

    Args:
        body (E964547412Ede512F9534970C8E3971ABody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Union[E964547412Ede512F9534970C8E3971AResponse200, ResponseError]]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: E964547412Ede512F9534970C8E3971ABody,
) -> Optional[Union[E964547412Ede512F9534970C8E3971AResponse200, ResponseError]]:
    """***Limit:*** 10 queries per second

    Args:
        body (E964547412Ede512F9534970C8E3971ABody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Union[E964547412Ede512F9534970C8E3971AResponse200, ResponseError]
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
