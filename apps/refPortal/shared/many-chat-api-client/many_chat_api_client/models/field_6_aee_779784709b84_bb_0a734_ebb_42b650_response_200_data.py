from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, Union

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.flow import Flow
    from ..models.folder import Folder


T = TypeVar("T", bound="Field6Aee779784709B84Bb0A734Ebb42B650Response200Data")


@_attrs_define
class Field6Aee779784709B84Bb0A734Ebb42B650Response200Data:
    """
    Attributes:
        flows (Union[Unset, list['Flow']]):
        folders (Union[Unset, list['Folder']]):
    """

    flows: Union[Unset, list["Flow"]] = UNSET
    folders: Union[Unset, list["Folder"]] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        flows: Union[Unset, list[dict[str, Any]]] = UNSET
        if not isinstance(self.flows, Unset):
            flows = []
            for flows_item_data in self.flows:
                flows_item = flows_item_data.to_dict()
                flows.append(flows_item)

        folders: Union[Unset, list[dict[str, Any]]] = UNSET
        if not isinstance(self.folders, Unset):
            folders = []
            for folders_item_data in self.folders:
                folders_item = folders_item_data.to_dict()
                folders.append(folders_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if flows is not UNSET:
            field_dict["flows"] = flows
        if folders is not UNSET:
            field_dict["folders"] = folders

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.flow import Flow
        from ..models.folder import Folder

        d = dict(src_dict)
        flows = []
        _flows = d.pop("flows", UNSET)
        for flows_item_data in _flows or []:
            flows_item = Flow.from_dict(flows_item_data)

            flows.append(flows_item)

        folders = []
        _folders = d.pop("folders", UNSET)
        for folders_item_data in _folders or []:
            folders_item = Folder.from_dict(folders_item_data)

            folders.append(folders_item)

        field_6_aee_779784709b84_bb_0a734_ebb_42b650_response_200_data = cls(
            flows=flows,
            folders=folders,
        )

        field_6_aee_779784709b84_bb_0a734_ebb_42b650_response_200_data.additional_properties = d
        return field_6_aee_779784709b84_bb_0a734_ebb_42b650_response_200_data

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
