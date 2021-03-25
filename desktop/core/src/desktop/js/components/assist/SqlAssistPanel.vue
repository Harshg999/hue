<template>
  <div>
    <SqlConnectorDropdown v-model="activeConnector" />
  </div>
  {{ activeConnector?.name }}
</template>

<script lang="ts">
  import { defineComponent, ref } from 'vue';

  import SqlConnectorDropdown from 'components/SqlConnectorDropdown.vue';
  import { EditorInterpreter } from 'config/types';
  import I18n from 'utils/i18n';

  export default defineComponent({
    name: 'SqlAssistPanel',
    components: { SqlConnectorDropdown },
    setup() {
      const activeConnector = ref<EditorInterpreter | null>();

      return { activeConnector, I18n };
    }
  });
</script>
