include_guard()

set(SDK_DIR ${TOP}/hw/mcu/microchip/samd21)

# include board specific
include(${CMAKE_CURRENT_LIST_DIR}/boards/${BOARD}/board.cmake)

# toolchain set up
set(CMAKE_SYSTEM_CPU cortex-m0plus CACHE INTERNAL "System Processor")
set(CMAKE_TOOLCHAIN_FILE ${TOP}/examples/build_system/cmake/toolchain/arm_${TOOLCHAIN}.cmake)

set(FAMILY_MCUS SAMD21 CACHE INTERNAL "")
set(OPENOCD_OPTION "-f interface/cmsis-dap.cfg -c \"transport select swd\" -f target/at91samdXX.cfg")

#------------------------------------
# BOARD_TARGET
#------------------------------------
# only need to be built ONCE for all examples
function(add_board_target BOARD_TARGET)
  if (TARGET ${BOARD_TARGET})
    return()
  endif ()

  set(LD_FILE_Clang ${LD_FILE_GNU})
  if (NOT DEFINED LD_FILE_${CMAKE_C_COMPILER_ID})
    message(FATAL_ERROR "LD_FILE_${CMAKE_C_COMPILER_ID} not defined")
  endif ()

  set(STARTUP_FILE_GNU ${SDK_DIR}/gcc/gcc/startup_samd21.c)
  set(STARTUP_FILE_Clang ${STARTUP_FILE_GNU})

  add_library(${BOARD_TARGET} STATIC
    ${SDK_DIR}/gcc/system_samd21.c
    ${SDK_DIR}/hpl/gclk/hpl_gclk.c
    ${SDK_DIR}/hpl/pm/hpl_pm.c
    ${SDK_DIR}/hpl/sysctrl/hpl_sysctrl.c
    ${SDK_DIR}/hal/src/hal_atomic.c
    ${STARTUP_FILE_${CMAKE_C_COMPILER_ID}}
    )
  target_include_directories(${BOARD_TARGET} PUBLIC
    ${SDK_DIR}
    ${SDK_DIR}/config
    ${SDK_DIR}/include
    ${SDK_DIR}/hal/include
    ${SDK_DIR}/hal/utils/include
    ${SDK_DIR}/hpl/pm
    ${SDK_DIR}/hpl/port
    ${SDK_DIR}/hri
    ${SDK_DIR}/CMSIS/Include
    )
  target_compile_definitions(${BOARD_TARGET} PUBLIC
    CONF_DFLL_OVERWRITE_CALIBRATION=0
    )

  update_board(${BOARD_TARGET})

  if (CMAKE_C_COMPILER_ID STREQUAL "GNU")
    target_link_options(${BOARD_TARGET} PUBLIC
      "LINKER:--script=${LD_FILE_GNU}"
      -nostartfiles
      --specs=nosys.specs --specs=nano.specs
      )
  elseif (CMAKE_C_COMPILER_ID STREQUAL "Clang")
    target_link_options(${BOARD_TARGET} PUBLIC
      "LINKER:--script=${LD_FILE_Clang}"
      )
  elseif (CMAKE_C_COMPILER_ID STREQUAL "IAR")
    target_link_options(${BOARD_TARGET} PUBLIC
      "LINKER:--config=${LD_FILE_IAR}"
      )
  endif ()
endfunction()


#------------------------------------
# Functions
#------------------------------------
function(family_configure_example TARGET RTOS)
  family_configure_common(${TARGET} ${RTOS})

  # Board target
  add_board_target(board_${BOARD})

  #---------- Port Specific ----------
  # These files are built for each example since it depends on example's tusb_config.h
  target_sources(${TARGET} PUBLIC
    # BSP
    ${CMAKE_CURRENT_FUNCTION_LIST_DIR}/family.c
    ${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../board.c
    )
  target_include_directories(${TARGET} PUBLIC
    # family, hw, board
    ${CMAKE_CURRENT_FUNCTION_LIST_DIR}
    ${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../../
    ${CMAKE_CURRENT_FUNCTION_LIST_DIR}/boards/${BOARD}
    )

  # Add TinyUSB target and port source
  family_add_tinyusb(${TARGET} OPT_MCU_SAMD21)
  target_sources(${TARGET} PUBLIC
    ${TOP}/src/portable/microchip/samd/dcd_samd.c
    ${TOP}/src/portable/microchip/samd/hcd_samd.c
    )
  target_link_libraries(${TARGET} PUBLIC board_${BOARD})

  # Flashing
  family_add_bin_hex(${TARGET})
  family_flash_jlink(${TARGET})
  #family_flash_openocd(${TARGET})
endfunction()
