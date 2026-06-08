from http import HTTPStatus
from typing import Any, Optional, Union

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.b6_ae_94031676b69a57_eb_2_ad_5_ea_1413f9_body import B6Ae94031676B69A57Eb2Ad5Ea1413F9Body
from ...models.response_error_with_code import ResponseErrorWithCode
from ...models.response_success import ResponseSuccess
from ...types import Response


def _get_kwargs(
    *,
    body: B6Ae94031676B69A57Eb2Ad5Ea1413F9Body,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/fb/sending/sendContent",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Optional[Union[ResponseErrorWithCode, ResponseSuccess]]:
    if response.status_code == 200:
        response_200 = ResponseSuccess.from_dict(response.json())

        return response_200
    if response.status_code == 400:
        response_400 = ResponseErrorWithCode.from_dict(response.json())

        return response_400
    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Response[Union[ResponseErrorWithCode, ResponseSuccess]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: B6Ae94031676B69A57Eb2Ad5Ea1413F9Body,
) -> Response[Union[ResponseErrorWithCode, ResponseSuccess]]:
    """Send content to subscriber

     ***Limit:*** 25 queries per second

    Args:
        body (B6Ae94031676B69A57Eb2Ad5Ea1413F9Body):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Union[ResponseErrorWithCode, ResponseSuccess]]
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
    body: B6Ae94031676B69A57Eb2Ad5Ea1413F9Body,
) -> Optional[Union[ResponseErrorWithCode, ResponseSuccess]]:
    """Send content to subscriber

     ***Limit:*** 25 queries per second

    Args:
        body (B6Ae94031676B69A57Eb2Ad5Ea1413F9Body):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Union[ResponseErrorWithCode, ResponseSuccess]
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: B6Ae94031676B69A57Eb2Ad5Ea1413F9Body,
) -> Response[Union[ResponseErrorWithCode, ResponseSuccess]]:
    """Send content to subscriber

     ***Limit:*** 25 queries per second

    Args:
        body (B6Ae94031676B69A57Eb2Ad5Ea1413F9Body):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Union[ResponseErrorWithCode, ResponseSuccess]]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: B6Ae94031676B69A57Eb2Ad5Ea1413F9Body,
) -> Optional[Union[ResponseErrorWithCode, ResponseSuccess]]:
    """Send content to subscriber

     ***Limit:*** 25 queries per second

    Args:
        body (B6Ae94031676B69A57Eb2Ad5Ea1413F9Body):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Union[ResponseErrorWithCode, ResponseSuccess]
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
