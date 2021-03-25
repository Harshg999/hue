<template>
  <div>
    <SqlAssistPanel />
  </div>
</template>

<script lang="ts">
  import { defineComponent } from 'vue';
  import SqlAssistPanel from './SqlAssistPanel.vue';

  export default defineComponent({
    name: 'AssistPanel',
    components: { SqlAssistPanel },
    setup() {
      return {};
    }
  });
</script>
