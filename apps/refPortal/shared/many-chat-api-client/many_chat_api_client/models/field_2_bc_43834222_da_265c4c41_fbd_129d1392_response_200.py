from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, Union

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.custom_field import CustomField


T = TypeVar("T", bound="Field2Bc43834222Da265C4C41Fbd129D1392Response200")


@_attrs_define
class Field2Bc43834222Da265C4C41Fbd129D1392Response200:
    """
    Attributes:
        status (Union[Unset, str]):  Example: success.
        data (Union[Unset, list['CustomField']]):
    """

    status: Union[Unset, str] = UNSET
    data: Union[Unset, list["CustomField"]] = UNSET
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
        from ..models.custom_field import CustomField

        d = dict(src_dict)
        status = d.pop("status", UNSET)

        data = []
        _data = d.pop("data", UNSET)
        for data_item_data in _data or []:
            data_item = CustomField.from_dict(data_item_data)

            data.append(data_item)

        field_2_bc_43834222_da_265c4c41_fbd_129d1392_response_200 = cls(
            status=status,
            data=data,
        )

        field_2_bc_43834222_da_265c4c41_fbd_129d1392_response_200.additional_properties = d
        return field_2_bc_43834222_da_265c4c41_fbd_129d1392_response_200

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
