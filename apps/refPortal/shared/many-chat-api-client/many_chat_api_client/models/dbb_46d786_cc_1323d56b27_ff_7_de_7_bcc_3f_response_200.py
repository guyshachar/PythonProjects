from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, Union

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.bot_field import BotField


T = TypeVar("T", bound="Dbb46D786Cc1323D56B27Ff7De7Bcc3FResponse200")


@_attrs_define
class Dbb46D786Cc1323D56B27Ff7De7Bcc3FResponse200:
    """
    Attributes:
        status (Union[Unset, str]):  Example: success.
        data (Union[Unset, list['BotField']]):
    """

    status: Union[Unset, str] = UNSET
    data: Union[Unset, list["BotField"]] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        status = self.status

        data: Union[Unset, list[dict[str, Any]]] = UNSET
        if not isinstance(self.data, Unset):
            data = []
            for data_item_data in self.data:
                data_item = data_item_data.to_dict()
                data.append(data_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if status is not UNSET:
            field_dict["status"] = status
        if data is not UNSET:
            field_dict["data"] = data

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.bot_field import BotField

        d = dict(src_dict)
        status = d.pop("status", UNSET)

        data = []
        _data = d.pop("data", UNSET)
        for data_item_data in _data or []:
            data_item = BotField.from_dict(data_item_data)

            data.append(data_item)

        dbb_46d786_cc_1323d56b27_ff_7_de_7_bcc_3f_response_200 = cls(
            status=status,
            data=data,
        )

        dbb_46d786_cc_1323d56b27_ff_7_de_7_bcc_3f_response_200.additional_properties = d
        return dbb_46d786_cc_1323d56b27_ff_7_de_7_bcc_3f_response_200

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
