<template>
  <DropdownMenu :if="connectors.length > 1" :link="true" :text="modelValue?.name || I18n('Source')">
    <DropdownMenuButton
      v-for="connector in connectors"
      :key="connector.id"
      @click="connectorSelected(connector)"
    >
      {{ connector.displayName }}
    </DropdownMenuButton>
  </DropdownMenu>
</template>

<script lang="ts">
  import { defineComponent, PropType, ref, toRefs } from 'vue';

  import DropdownMenuButton from './dropdown/DropdownMenuButton.vue';
  import DropdownMenu from './dropdown/DropdownMenu.vue';
  import SubscriptionTracker from './utils/SubscriptionTracker';
  import { EditorInterpreter } from 'config/types';
  import { filterEditorConnectors, getConfig } from 'config/hueConfig';
  import { CONFIG_REFRESHED_TOPIC, ConfigRefreshedEvent } from 'config/events';
  import I18n from 'utils/i18n';

  export default defineComponent({
    name: 'SqlConnectorDropdown',
    components: { DropdownMenuButton, DropdownMenu },
    props: {
      modelValue: {
        type: Object as PropType<EditorInterpreter | null>,
        default: null
      }
    },
    emits: ['update:model-value'],
    setup(props, { emit }) {
      const { modelValue } = toRefs(props);
      const subTracker = new SubscriptionTracker();
      const connectors = ref<EditorInterpreter[]>([]);

      const connectorSelected = (connector: EditorInterpreter | null) => {
        emit('update:model-value', connector);
      };

      const updateSources = () => {
        connectors.value = filterEditorConnectors(connector => connector.is_sql);

        let updatedConnector: EditorInterpreter | undefined = undefined;
        // Set the activeConnector to 1. updated version, 2. same dialect, 3. first connector
        if (modelValue.value) {
          updatedConnector =
            connectors.value.find(connector => connector.id === modelValue.value!.id) ||
            connectors.value.find(connector => connector.dialect === modelValue.value!.dialect);
        }
        if (!updatedConnector && connectors.value.length) {
          updatedConnector = connectors.value[0];
        }
        connectorSelected(updatedConnector || null);
      };

      getConfig().then(updateSources);
      subTracker.subscribe<ConfigRefreshedEvent>(CONFIG_REFRESHED_TOPIC, updateSources);

      return { connectors, connectorSelected, I18n };
    }
  });
</script>
